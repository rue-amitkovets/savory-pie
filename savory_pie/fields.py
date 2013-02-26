class AttributeField(object):
    """
    Simple Field that translates an object property to/from a dict.

        Parameters:

            ``attribute``
                attribute on the Model can be a multi-level expression - like
                related_entity.attribute

            ``type``
                expecting type of value -- int, bool, etc.

            ``published_property``
                optional -- name exposed in the API

            ``use_prefetch``
                optional -- tells the attribute field to use
                prefetch_related rather than a select_related.  Defaults to false.

                There are two reasons you might need to do this...

                - select_related will not work when the foreign key allows null.
                - select_related will not work when the foreign key is a GenericForeignKey.

                See https://docs.djangoproject.com/en/dev/ref/models/querysets/

                This parameter is meaningless for top-level attributes.

        .. code-block:: python

            AttributeField('name', type=str)

        .. code-block:: javascript

            {'name': obj.name}

        .. code-block:: python

            AttributeField('other.age', type=int)

        .. code-block:: javascript

           {'age': obj.other.age}
    """
    def __init__(self, attribute, type, published_property=None, use_prefetch=False):
        self._full_attribute = attribute
        self._type = type
        self._published_property = published_property
        self._use_prefetch = use_prefetch

    def _compute_property(self, ctx):
        if self._published_property is not None:
            return self._published_property
        else:
            return ctx.formatter.default_published_property(self._bare_attribute)

    @property
    def _bare_attribute(self):
        return self._full_attribute.split('.')[-1]

    @property
    def _attrs(self):
        return self._full_attribute.split('.')

    def _get_object(self, root_obj):
        obj = root_obj
        for attr in self._attrs[:-1]:
            obj = getattr(obj, attr)
            if obj is None:
                return None
        return obj

    def _get(self, obj):
        obj = self._get_object(obj)
        if obj is None:
            return None
        else:
            return getattr(obj, self._bare_attribute)

    def _set(self, obj, value):
        obj = self._get_object(obj)
        # TODO: handle None
        return setattr(obj, self._bare_attribute, value)

    def handle_incoming(self, ctx, source_dict, target_obj):
        self._set(
            target_obj,
            self.to_python_value(ctx, source_dict[self._compute_property(ctx)])
        )

    def handle_outgoing(self, ctx, source_obj, target_dict):
        target_dict[self._compute_property(ctx)] = self.to_api_value(
            ctx,
            self._get(source_obj)
        )

    def to_python_value(self, ctx, api_value):
        return ctx.formatter.to_python_value(self._type, api_value)

    def to_api_value(self, ctx, python_value):
        return ctx.formatter.to_api_value(self._type, python_value)

    def prepare(self, ctx, related):
        related_attr = '__'.join(self._attrs[:-1])
        if related_attr:
            if self._use_prefetch:
                related.prefetch(related_attr)
            else:
                related.select(related_attr)


class URIResourceField(object):
    """
    Field that exposes just the URI of related entity


    Parameters:

        ``attribute``
            name of the relationship between the parent object and the related
            object may only be single level

        ``resource_class``
            a ModelResource -- used to represent the related object needs to be
            fully addressable

        ``published_property``
            optional -- name exposed in the API


        .. code-block:: python

            URIResourceField('other', OtherResource)

        .. code-block:: javascript

            {'other': '/api/other/{pk}'}
    """
    def __init__(self, attribute, resource_class, published_property=None):
        self._attribute = attribute
        self._resource_class = resource_class
        self._published_property = published_property

    def _compute_property(self, ctx):
        if self._published_property is not None:
            return self._published_property
        else:
            return ctx.formatter.default_published_property(self._attribute)

    def handle_incoming(self, ctx, source_dict, target_obj):
        uri = source_dict[self._compute_property(ctx)]

        resource = ctx.resolve_resource_uri(uri)
        if resource is None:
            raise ValueError, 'invalid URI: ' + uri

        setattr(target_obj, self._attribute, resource.model)

    def handle_outgoing(self, ctx, source_obj, target_dict):
        sub_model = getattr(source_obj, self._attribute)
        resource = self._resource_class(sub_model)

        target_dict[self._compute_property(ctx)] = ctx.build_resource_uri(resource)

    def prepare(self, ctx, related):
        related.select(self._attribute)
        self._resource_class.prepare(ctx, related.sub_select(self._attribute))


class SubModelResourceField(object):
    """
    Field that embeds a single related resource into the parent object

    Parameters:

        ``attribute``
            name of the relationship between the parent object and the related
            object may only be single level

        ``resource_class``
            a ModelResource -- used to represent the related object

        ``published_property``
            optional -- name exposed in the API

        ``use_prefetch``
            optional -- tells the sub-model resource field to use
            prefetch_related rather than a select_related.  Defaults to false.

            There are two reasons you might need to do this...

            - select_related will not work when the foreign key allows null.
            - select_related will not work when the foreign key is a GenericForeignKey.

            See https://docs.djangoproject.com/en/dev/ref/models/querysets/

        .. code-block:: python

            SubModelResourceField('other', OtherResource)

        .. code-block:: javascript

            {'other': {'age': 9}}
    """
    def __init__(self, attribute, resource_class, published_property=None, use_prefetch=False):
        self._attribute = attribute
        self._resource_class = resource_class
        self._published_property = published_property
        self._use_prefetch = use_prefetch

    def _compute_property(self, ctx):
        if self._published_property is not None:
            return self._published_property
        else:
            return ctx.formatter.default_published_property(self._attribute)

    def handle_incoming(self, ctx, source_dict, target_obj):
        sub_model = getattr(target_obj, self._attribute, None)
        if sub_model is None:
            sub_resource = self._resource_class.create_resource()
            # I am not 100% happy with this
            setattr(target_obj, self._attribute, sub_resource.model)
        else:
            sub_resource = self._resource_class(sub_model)

        sub_resource.put(ctx, source_dict[self._compute_property(ctx)])

    def handle_outgoing(self, ctx, source_obj, target_dict):
        sub_model = getattr(source_obj, self._attribute)
        target_dict[self._compute_property(ctx)] = self._resource_class(sub_model).get(ctx)

    def prepare(self, ctx, related):
        if self._use_prefetch:
            related.prefetch(self._attribute)
            self._resource_class.prepare(ctx, related.sub_prefetch(self._attribute))
        else:
            related.select(self._attribute)
            self._resource_class.prepare(ctx, related.sub_select(self._attribute))


class RelatedManagerField(object):
    """
    Field that embeds a many relationship into the parent object

    Parameters:

        ``attribute``
            name of the relationship between the parent object and the related
            objects may only be single level

        ``resource_class``
            a ModelResource -- used to represent the related objects

        ``published_property``
            optional name exposed through the API

        .. code-block:: python

            RelatedManagerField('others', OtherResource)

        .. code-block:: javascript

            {'others': [{'age': 6}, {'age': 1}]}
    """
    def __init__(self, attribute, resource_class, published_property=None):
        self._attribute = attribute
        self._resource_class = resource_class
        self._published_property = published_property

    def _compute_property(self, ctx):
        if self._published_property is not None:
            return self._published_property
        else:
            return ctx.formatter.default_published_property(self._attribute)

    def handle_incoming(self, ctx, source_dict, target_obj):
        manager = getattr(target_obj, self._attribute)

        db_keys = set()
        db_models = {}
        for model in manager.all():
            resource = self._resource_class(model)
            db_models[resource.key] = model
            db_keys.add(resource.key)

        new_models = []
        request_keys = set()
        request_models = {}
        for model_dict in source_dict[self._compute_property(ctx)]:
            if '_id' in model_dict: # TODO what if you give an id that is not in the db?
                # TODO get key without the extra db lookup
                model = self._resource_class.get_from_queryset(manager.all(), model_dict['_id'])
                model_resource = self._resource_class(model)
                request_models[model_resource.key] = model_resource.model
                request_keys.add(model_resource.key)
                if model_resource.key in db_keys:
                    model_resource.put(ctx, model_dict)
            else:
                model_resource = self._resource_class.create_resource()
                model_resource.put(ctx, model_dict)
                new_models.append(model_resource.model)

        manager.add(*new_models)

        models_to_remove = [db_models[key] for key in db_keys - request_keys]
        # If the FK is not nullable the manager will not have a remove
        if hasattr(manager, 'remove'):
            manager.remove(*models_to_remove)
        else:
            for model in models_to_remove:
                model.delete()

    def handle_outgoing(self, ctx, source_obj, target_dict):
        manager = getattr(source_obj, self._attribute)
        objects = []
        for model in manager.all():
            model_resource = self._resource_class(model)
            model_dict = model_resource.get(ctx)
            # TODO only add _id if there is not a resource_url
            model_dict['_id'] = model_resource.key
            objects.append(model_dict)
        target_dict[self._compute_property(ctx)] = objects

    def prepare(self, ctx, related):
        related.prefetch(self._attribute)
        self._resource_class.prepare(ctx, related.sub_prefetch(self._attribute))
