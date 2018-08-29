import unittest
import django
from UserDict import UserDict

import mock
from mock import Mock
import django.db.models

from django.core.exceptions import ObjectDoesNotExist

from savory_pie.django import resources, fields
from savory_pie.django.fields import (
    AttributeField,
    AttributeFieldWithModel,
    OneToOneField,
    RelatedManagerField,
    SubModelResourceField,
    URIListResourceField,
    URIResourceField,
    AggregateField, RelatedCountField)
from savory_pie.django.resources import ModelResource, QuerySetResource
from savory_pie.django.utils import Related
from savory_pie.errors import SavoryPieError
from savory_pie.django.validators import ValidationError
from savory_pie.tests.django import mock_orm
from savory_pie.tests.django.mock_request import mock_context


class AttributeFieldTest(unittest.TestCase):
    def test_simple_outgoing(self):
        source_object = Mock()
        source_object.foo = 20

        target_dict = dict()

        field = AttributeField(attribute='foo', type=int)
        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], 20)

    def test_simple_none_outgoing(self):
        source_object = Mock()
        source_object.foo = None

        target_dict = dict()

        field = AttributeField(attribute='foo', type=int)
        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], None)

    def test_multilevel_outgoing(self):
        source_object = Mock()
        source_object.foo.bar = 20

        field = AttributeField(attribute='foo.bar', type=int)

        target_dict = dict()

        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['bar'], 20)

    def test_multilevel_incoming(self):
        source_dict = {
            'bar': 20
        }

        field = AttributeField(attribute='foo.bar', type=int)

        target_object = Mock(name='target')

        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(target_object.foo.bar, 20)

    def test_simple_incoming(self):
        source_dict = {
            'foo': 20
        }

        target_object = Mock(name='target')

        field = AttributeField(attribute='foo', type=int)
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(target_object.foo, 20)

    def test_incoming_pushes_and_pops(self):
        source_dict = {
            'foo': 20
        }
        ctx = mock_context()

        target_object = Mock(name='target')

        field = AttributeField(attribute='foo', type=int)
        field.handle_incoming(ctx, source_dict, target_object)

        ctx.assert_has_calls([
            mock.call.push(target_object),
            mock.call.pop(),
        ])

    def test_save(self):
        target_object = Mock(name='target')

        field = AttributeField(attribute='foo', type=int)
        field.save(target_object)

        self.assertTrue(target_object.save.called)

    def test_incoming_read_only(self):
        source_dict = {
            'foo': 20
        }

        target_object = Mock(name='target', spec=[])

        field = AttributeField(attribute='foo', type=int, read_only=True)
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertFalse(hasattr(target_object, 'foo'))

    def test_simple_none_incoming(self):
        source_dict = {
            'foo': None
        }

        target_object = Mock(name='target')

        field = AttributeField(attribute='foo', type=int)
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(target_object.foo, None)

    def test_simple_missing_incoming(self):
        source_dict = {}

        target_object = Mock(name='target')

        field = AttributeField(attribute='foo', type=int)
        with self.assertRaises(ValidationError):
            field.handle_incoming(mock_context(), source_dict, target_object)

    def test_alternate_name_outgoing(self):
        source_object = Mock()
        source_object.foo.bar = 20

        field = AttributeField(attribute='foo.bar', type=int, published_property='foo')

        target_dict = dict()

        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], 20)

    def test_alternate_name_incoming(self):
        source_dict = {
            'foo': 20
        }

        field = AttributeField(attribute='foo.bar', type=int, published_property='foo')

        target_object = Mock(name='target')

        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(target_object.foo.bar, 20)

    def test_published_property_camel_case(self):
        source_object = Mock()
        source_object.foo.bar = 20

        field = AttributeField(attribute='foo.bar', type=int, published_property='foo_bar')

        target_dict = dict()

        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['fooBar'], 20)

    def test_prepare(self):
        field = AttributeField(attribute='foo.bar.baz', type=int)

        related = Related()
        field.prepare(mock_context(), related)

        self.assertEqual(related._select, {
            'foo__bar'
        })

    def test_prepare_with_use_prefetch(self):
        field = AttributeField(attribute='foo.bar.baz', type=int, use_prefetch=True)

        related = Related()
        field.prepare(mock_context(), related)

        self.assertEqual(related._prefetch, {
            'foo__bar'
        })

    def test_add_field(self):
        field = AttributeField(attribute='foo', type=int)
        source_dict = {'foo': 3}
        filter_args = {}

        field.filter_by_item(mock_context(), filter_args, source_dict)

        self.assertEqual({'foo': 3}, filter_args)


class AttributeFieldWithModelsTest(unittest.TestCase):
    def setUp(self):
        class CharField(Mock):
            pass

        class ForeignKey(Mock):
            pass

        class mock_Model(mock_orm.Model):
            def __getattribute__(self, item):
                result = super(mock_Model, self).__getattribute__(item)
                if item in ['bar', 'baz']:
                    result = result.target
                return result

        class BazModel(mock_Model):
            potato = CharField()
            potato.name = 'potato'
            other = CharField()
            other.name = 'other'
        self.baz = BazModel(potato='idaho')
        BazModel._meta = Mock()
        BazModel._meta.fields = [BazModel.potato, BazModel.other]
        self.BazModel = BazModel

        class BarModel(mock_Model):
            baz = ForeignKey()
            baz.name = 'baz'
            baz.target = self.baz
        my_bar = BarModel()
        BarModel._meta = Mock()
        BarModel._meta.fields = [BarModel.baz]

        class FooModel(mock_Model):
            bar = ForeignKey('bar', BarModel())
            bar.name = 'bar'
            bar.target = my_bar
        FooModel._meta = Mock()
        FooModel._meta.fields = [FooModel.bar]
        self.foo = FooModel()

    def test_simple_incoming(self):
        field = AttributeFieldWithModel(
            attribute='bar.baz.potato',
            type=str,
            model=self.BazModel
        )

        source_dict = {
            'potato': 'abc'
        }
        field.handle_incoming(mock_context(), source_dict, self.foo)
        self.assertEqual(self.baz.potato, 'abc')

    def test_simple_incoming_with_extras(self):
        field = AttributeFieldWithModel(
            attribute='bar.baz.potato',
            type=str,
            model=self.BazModel,
            extras={'other': 'def'}
        )

        source_dict = {
            'potato': 'abc'
        }
        field.handle_incoming(mock_context(), source_dict, self.foo)
        self.assertEqual(self.baz.potato, 'abc')
        self.assertEqual(self.baz.other, 'def')


class URIResourceFieldTest(unittest.TestCase):
    def test_outgoing(self):

        class Resource(ModelResource):
            model_class = Mock()
            parent_resource_path = 'resources'

        field = URIResourceField(attribute='foo', resource_class=Resource)

        source_object = Mock()
        source_object.foo = mock_orm.Model(pk=2)

        target_dict = dict()
        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], 'uri://resources/2')

    def test_incoming(self):

        class Resource(ModelResource):
            model_class = Mock()
            pass

        field = URIResourceField(attribute='foo', resource_class=Resource)

        source_dict = {
            'foo': 'uri://resources/2'
        }
        target_object = Mock()

        related_model = mock_orm.Model(pk=2)

        ctx = mock_context()
        ctx.resolve_resource_uri = Mock(return_value=Resource(related_model))

        field.handle_incoming(ctx, source_dict, target_object)

        ctx.resolve_resource_uri.assert_called_with('uri://resources/2')
        self.assertEqual(target_object.foo, related_model)

    def test_incoming_read_only(self):

        class Resource(ModelResource):
            model_class = Mock()
            pass

        field = URIResourceField(
            attribute='foo',
            resource_class=Resource,
            read_only=True,
        )

        source_dict = {
            'foo': 'uri://resources/2'
        }
        target_object = Mock([])

        related_model = mock_orm.Model(pk=2)

        ctx = mock_context()
        ctx.resolve_resource_uri = Mock(return_value=Resource(related_model))

        field.handle_incoming(ctx, source_dict, target_object)

        self.assertFalse(ctx.resolve_resource_uri.called)
        self.assertFalse(hasattr(target_object, 'foo'))


class SchemaSubfieldFieldTest(unittest.TestCase):
    def test_schema_subfield(self):

        class SubResource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='foo', type=int),
            ]

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
                RelatedManagerField(attribute='baz', resource_class=SubResource),
            ]

        resource = resources.SchemaResource(Resource)
        ctx = mock_context()
        ctx.build_resource_uri = lambda resource: 'uri://user/schema/'
        schema = resource.get(ctx)
        self.assertTrue('fields' in schema)
        self.assertTrue('bar' in schema['fields'])
        self.assertTrue('baz' in schema['fields'])
        self.assertTrue('fields' in schema['fields']['baz'])
        self.assertTrue('foo' in schema['fields']['baz']['fields'])


class SubModelResourceFieldTest(unittest.TestCase):
    def test_outgoing(self):

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_object = Mock()
        source_object.foo.bar = 20

        target_dict = dict()

        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], {'bar': 20})

    def test_outgoing_with_simple_none(self):

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_object = Mock()
        source_object.foo.bar = None

        target_dict = dict()

        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], {'bar': None})

    def test_outgoing_with_submodel_none(self):

        class OtherResource(ModelResource):
            model_class = Mock()
            field = [
                AttributeField(attribute='bar', type=int),
            ]

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                SubModelResourceField(attribute='bar', resource_class=OtherResource),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_object = Mock()
        source_object.foo = None

        target_dict = dict()

        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], None)

    def test_incoming_update_existing(self):

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_dict = {
            'foo': {'bar': 20},
        }

        target_object = Mock()
        target_object._meta.get_field().related.field.name = 'bar'
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(target_object.foo.bar, 20)
        target_object.foo.save.assert_called_with()

    @mock.patch('savory_pie.fields.AttributeField._get_object')
    def test_incoming_update_not_dirty(self, get_object):
        target = Mock()
        target.is_dirty.return_value = False
        get_object.return_value = target

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_dict = {
            'foo': {'bar': 20},
        }
        target_object = Mock()
        target_object._meta.get_field().related.field.name = 'bar'
        field.handle_incoming(mock_context(), source_dict, target_object)
        self.assertFalse(target.save.called)

    def test_incoming_with_none_source(self):

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_dict = {}

        target_object = Mock()

        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(target_object.foo, None)

    def test_incoming_with_none_source_with_not_none_existing(self):
        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_dict = {
            'foo': None
        }

        target_object = Mock()
        target_object.foo = UserDict({'bar': 4})
        target_object.foo.pk = 1
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(target_object.foo, None)

    def test_incoming_with_none_subresource(self):

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=Resource)

        source_dict = {
            'foo': {}
        }

        target_object = Mock()
        target_object._meta.get_field().related.field.name = 'bar'
        field.handle_incoming(mock_context(), source_dict, target_object)
        self.assertIsNotNone(target_object.foo)

    def test_incoming_read_only(self):

        class Resource(ModelResource):
            model_class = Mock(spec=[])
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(
            attribute='foo',
            resource_class=Resource,
            read_only=True,
        )

        source_dict = {
            'foo': {'bar': 20},
        }

        target_object = Mock()
        target_object.foo = Mock(['save'])

        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertFalse(hasattr(target_object.foo, 'bar'))
        self.assertFalse(target_object.foo.save.called)

    def test_new_object_incoming(self):

        class MockResource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

            @classmethod
            def get_by_source_dict(cls, ctx, sub_source_dict):
                return None

        field = SubModelResourceField(attribute='foo', resource_class=MockResource)

        source_dict = {
            'foo': {'bar': 20},
        }

        # The django ORM makes me sad that this is not a None or AttributeError
        class MockFailsOnFooAccess(Mock):
            def __getattr__(self, name):
                if name == 'foo':
                    raise ObjectDoesNotExist
                else:
                    return super(Mock, self).__getattr__(name)

        target_object = MockFailsOnFooAccess()
        target_object._meta.get_field().related.field.name = 'bar'
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(20, target_object.foo.bar)
        self.assertEqual(MockResource.model_class.return_value, target_object.foo)
        target_object.foo.save.assert_called()

    def test_find_existing_incoming(self):

        mock_model = Mock()

        class MockResource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

            @classmethod
            def get_by_source_dict(cls, ctx, sub_source_dict):
                return cls(mock_model)

        field = SubModelResourceField(attribute='foo', resource_class=MockResource)

        source_dict = {
            'foo': {'bar': 20},
        }

        # The django ORM makes me sad that this is not a None or AttributeError
        class MockFailsOnFooAccess(Mock):
            def __getattr__(self, name):
                if name == 'foo':
                    raise ObjectDoesNotExist
                else:
                    return super(Mock, self).__getattr__(name)

        target_object = MockFailsOnFooAccess()
        target_object._meta.get_field().related.field.name = 'bar'
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(20, target_object.foo.bar)
        self.assertEqual(mock_model, target_object.foo)
        target_object.foo.save.assert_called()

    def test_find_existing_by_uri_incoming(self):

        class MockResource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=MockResource)

        source_dict = {
            'foo': {
                'resourceUri': 'http://testsever/api/v1/bar/20',
                'bar': 20
            },
        }

        target_object = Mock()
        target_object._meta.get_field().related.field.name = 'bar'
        ctx = mock_context()
        ctx.resolve_resource_uri = Mock()
        foo_20 = ctx.resolve_resource_uri.return_value = MockResource(Mock())
        field.handle_incoming(ctx, source_dict, target_object)

        ctx.resolve_resource_uri.assert_called_with(source_dict['foo']['resourceUri'])
        target_object.foo.save.assert_called()

        self.assertEqual(foo_20.model, target_object.foo)
        self.assertEqual(20, target_object.foo.bar)

    def test_incoming_with_reverse_foreign_key(self):
        class User(mock_orm.Model):
            name = Mock()

        class UserOwner(mock_orm.Model):
            user = Mock(django.db.models.fields.related.ReverseSingleRelatedObjectDescriptor(Mock()))
            type = Mock()

        class UserOwnerResource(resources.ModelResource):
            model_class = UserOwner

            fields = [
                fields.AttributeField(attribute='type', type=str),
            ]

        class MockResource(ModelResource):
            model_class = User

            owner_field = fields.SubModelResourceField(attribute='owner', resource_class=UserOwnerResource)
            fields = [
                AttributeField(attribute='name', type=str),
                owner_field
            ]

        field = SubModelResourceField(attribute='user', resource_class=MockResource)

        source_dict = {
            'user': {'name': 'username', 'owner': {'type': 'ownertype'}},
        }

        # The django ORM makes me sad that this is not a None or AttributeError
        class MockFailsOnFooAccess(Mock):
            def model(self):
                return Mock()

            def __getattr__(self, name):
                if name == 'user':
                    raise ObjectDoesNotExist
                else:
                    return super(Mock, self).__getattr__(name)

        target_object = MockFailsOnFooAccess()
        target_object._meta.get_field().related.field.name = 'name'
        User.objects.filter().get()._meta.get_field().related.field.name = 'name'

        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual('username', target_object.user.name)
        self.assertEqual('ownertype', target_object.user.owner.type)
        target_object.user.save.assert_called()

    def test_prepare(self):

        class MockResource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar.baz', type=int),
            ]

        field = SubModelResourceField(attribute='foo', resource_class=MockResource)

        related = Related()
        field.prepare(mock_context(), related)

        self.assertEqual(related._select, {
            'foo',
            'foo__bar'
        })

    def test_prepare_with_use_prefetch(self):

        class MockResource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar.baz', type=int),
            ]

        field = SubModelResourceField(
            attribute='foo',
            resource_class=MockResource,
            use_prefetch=True
        )

        related = Related()
        field.prepare(mock_context(), related)

        self.assertEqual(related._prefetch, {
            'foo',
            'foo__bar'
        })


class OneToOneFieldTest(unittest.TestCase):
    def test_outgoing(self):

        class Resource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = OneToOneField(attribute='foo', resource_class=Resource)

        source_object = Mock()
        source_object.foo.bar = 20

        target_dict = dict()

        field.handle_outgoing(mock_context(), source_object, target_dict)

        self.assertEqual(target_dict['foo'], {'bar': 20})

    def test_new_object_incoming(self):

        class MockResource(ModelResource):
            model_class = Mock()
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = OneToOneField(attribute='foo', resource_class=MockResource)

        source_dict = {
            'foo': {'bar': 20},
        }

        # The django ORM makes me sad that this is not a None or AttributeError
        class MockFailsOnFooAccess(Mock):
            def __getattr__(self, name):
                if name == 'foo':
                    raise ObjectDoesNotExist
                else:
                    return super(Mock, self).__getattr__(name)

        target_object = MockFailsOnFooAccess()
        target_object._meta.get_field().related.field.name = 'bar'
        field.handle_incoming(mock_context(), source_dict, target_object)

        self.assertEqual(20, target_object.foo.bar)
        self.assertEqual(MockResource.model_class.return_value, target_object.foo)
        target_object.foo.save.assert_called()


class RelatedManagerFieldTest(unittest.TestCase):
    def test_outgoing(self):

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = RelatedManagerField(attribute='foo', resource_class=MockResource)

        source_object = mock_orm.Model()
        related_manager = mock_orm.Manager()
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            mock_orm.Model(pk=4, bar=14)
        ))
        source_object.foo = related_manager

        target_dict = {}
        field.handle_outgoing(mock_context(), source_object, target_dict)
        self.assertEqual([{'_id': '4', 'bar': 14}], target_dict['foo'])

    def test_outgoing_with_resource_uri(self):

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            resource_path = 'bar'
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = RelatedManagerField(attribute='foo', resource_class=MockResource)

        source_object = mock_orm.Model()
        related_manager = mock_orm.Manager()
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            mock_orm.Model(pk=4, bar=14)
        ))
        source_object.foo = related_manager

        target_dict = {}

        field.handle_outgoing(mock_context(), source_object, target_dict)
        target = target_dict['foo']
        # Not testing the hash of the dictionary that is tested else were
        self.assertEqual(
            [{'resourceUri': 'uri://bar', 'bar': 14}],
            target
        )

    def test_prepare(self):

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField('bar.baz', type=int)
            ]

        class MockQuerySetResource(QuerySetResource):
            resource_class = MockResource

        field = RelatedManagerField(attribute='foo', resource_class=MockQuerySetResource)

        related = Related()
        field.prepare(mock_context(), related)

        self.assertEqual(related._prefetch, {
            'foo',
            'foo__bar'
        })

    def test_incoming_no_id(self):
        del mock_orm.Model._models[:]

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = RelatedManagerField(attribute='foo', resource_class=MockResource)

        target_obj = mock_orm.Mock()
        related_manager = mock_orm.Manager()
        related_manager.all = Mock(return_value=mock_orm.QuerySet())
        target_obj.foo = related_manager
        source_dict = {
            'foo': [{'bar': 4}],
        }

        model_index = len(mock_orm.Model._models)
        field.handle_incoming(mock_context(), source_dict, target_obj)

        model = mock_orm.Model._models[model_index]
        self.assertEqual(4, model.bar)
        related_manager.add.assert_called_with(model)

    def test_incoming_with_resource_uri(self):
        del mock_orm.Model._models[:]

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = RelatedManagerField(attribute='foo', resource_class=MockResource)

        target_obj = mock_orm.Mock()

        related_manager = mock_orm.Manager()
        related_model = mock_orm.Model(pk=4, bar=10)
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            related_model
        ))
        target_obj.foo = related_manager
        source_dict = {
            'foo': [{
                'resourceUri': 'http://testsever/api/v2/bar/4',
                'bar': 14
            }],
        }

        model_index = len(mock_orm.Model._models)
        ctx = mock_context()
        ctx.resolve_resource_uri = Mock()
        ctx.resolve_resource_uri.return_value = MockResource(related_model)

        field.handle_incoming(ctx, source_dict, target_obj)
        model = mock_orm.Model._models[model_index - 1]
        self.assertEqual(14, model.bar)

    def test_incoming_delete(self):
        del mock_orm.Model._models[:]

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = RelatedManagerField(attribute='foo', resource_class=MockResource)

        target_obj = mock_orm.Mock()
        related_manager = mock_orm.Manager()
        related_model = mock_orm.Model(pk=4, bar=14)
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            related_model
        ))
        target_obj.foo = related_manager
        source_dict = {
            'foo': [],
        }

        field.handle_incoming(mock_context(), source_dict, target_obj)

        related_manager.remove.assert_called_with(related_model)

    def test_incoming_m2m_add(self):
        """
        Attempting to simulate the following:

        Bar(Model):
            pass

        Foo(Model):
            bars = ManyToManyField(Bar, through='FooBar')

        FooBar(Model):
            bar: ForeignKey(Bar)
            foo: ForeignKey(Foo)

        BarResource(ModelResource):
            model_class = Bar

        FooResource(ModelResource):
            model_class = Foo

            fields = [
                RelatedManagerField('bars', BarResource),
            ]
        """
        class BarResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='some_attribute', type=int),
            ]

        field = RelatedManagerField(attribute='bars', resource_class=BarResource)

        bar = mock_orm.Model(pk=1, someAttribute=1, resourceUri='bar/1')
        foo = mock_orm.Model(pk=2)

        BarResource.key = 'bar'
        BarResource.model = bar

        foobars = mock_orm.QuerySet()
        foobars.create = Mock(return_value=mock_orm.Model(pk=3, foo=foo, bar=bar))

        foobar = mock_orm.Model()
        foobar.objects = foobars

        foo.bars = mock_orm.Manager()
        foo.bars.source_field_name = 'foo'
        foo.bars.target_field_name = 'bar'
        foo.bars.all = Mock(return_value=mock_orm.QuerySet())
        foo.bars.through = foobar
        delattr(foo.bars, 'add')

        source_dict = {
            'bars': [bar.__dict__],
        }

        ctx = mock_context()
        ctx.resolve_resource_uri = Mock(return_value=BarResource)

        field.handle_incoming(ctx, source_dict, foo)

        foobars.create.assert_called_with(foo=foo, bar=bar)

    def test_incoming_m2m_delete(self):
        """
        Attempting to simulate the following:

        Bar(Model):
            pass

        Foo(Model):
            bars = ManyToManyField(Bar, through='FooBar')

        FooBar(Model):
            bar: ForeignKey(Bar)
            foo: ForeignKey(Foo)

        BarResource(ModelResource):
            model_class = Bar

        FooResource(ModelResource):
            model_class = Foo

            fields = [
                RelatedManagerField('bars', BarResource),
            ]
        """
        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='some_attribute', type=int),
            ]

        field = RelatedManagerField(attribute='bars', resource_class=MockResource)

        bar = mock_orm.Model(pk=1)
        foo = mock_orm.Model(pk=2)
        foobar = mock_orm.Model(pk=3, foo=foo, bar=bar)

        foobars = mock_orm.Manager()
        foobars.all = Mock(return_value=mock_orm.QuerySet(foobar))
        foobars.filter = foobars.all
        foobar.objects = foobars

        foo.bars = mock_orm.Manager()
        foo.bars.source_field_name = 'foo'
        foo.bars.target_field_name = 'bar'
        foo.bars.all = Mock(return_value=mock_orm.QuerySet(bar))
        foo.bars.through = foobar
        delattr(foo.bars, 'remove')

        source_dict = {
            'bars': [],
        }

        field.handle_incoming(mock_context(), source_dict, foo)

        foobar.delete.assert_called_with()

    def test_incoming_edit(self):
        del mock_orm.Model._models[:]

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = RelatedManagerField(attribute='foo', resource_class=MockResource)

        target_obj = mock_orm.Mock()
        related_manager = mock_orm.Manager()
        related_model = mock_orm.Model(pk=4, bar=14)
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            related_model
        ))
        target_obj.foo = related_manager
        source_dict = {
            'foo': [{'_id': '4', 'bar': 15}],
        }

        field.handle_incoming(mock_context(), source_dict, target_obj)

        self.assertEqual(15, related_model.bar)

    def test_incoming_read_only(self):
        del mock_orm.Model._models[:]

        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = RelatedManagerField(
            attribute='foo',
            resource_class=MockResource,
            read_only=True,
        )

        target_obj = mock_orm.Mock()
        related_manager = mock_orm.Manager()
        related_model = mock_orm.Model(pk=4, bar=14)
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            related_model
        ))
        target_obj.foo = related_manager
        source_dict = {
            'foo': [{'_id': '4', 'bar': 15}],
        }

        field.handle_incoming(mock_context(), source_dict, target_obj)

        self.assertEqual(14, related_model.bar)


class URIListResourceFieldTestCase(unittest.TestCase):

    def test_incoming_with_add(self):
        class MockResource(ModelResource):
            key = Mock()
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = URIListResourceField(attribute='foos', resource_class=MockResource)

        source_dict = {
            'foos': ['uri://resources/1', 'uri://resources/2']
        }

        target_object = mock_orm.Mock()
        related_manager = mock_orm.Manager()
        related_manager.all = Mock(return_value=mock_orm.QuerySet())
        target_object.foos = related_manager

        ctx = mock_context()
        foo1_model = Mock()
        foo2_model = Mock()
        mock_resources = Mock()
        resource1 = MockResource(foo1_model)
        resource1.key = 1
        resource2 = MockResource(foo2_model)
        resource2.key = 2
        mock_resources.side_effect = [resource1, resource2]

        ctx.resolve_resource_uri = mock_resources

        field.handle_incoming(ctx, source_dict, target_object)
        related_manager.add.assert_called_with(foo1_model, foo2_model)

    def test_incoming_with_delete(self):
        class MockResource(ModelResource):
            key = Mock()
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = URIListResourceField(attribute='foos', resource_class=MockResource)

        source_dict = {
            'foos': ['uri://resources/1', 'uri://resources/2']
        }

        target_object = mock_orm.Mock()
        related_manager = mock_orm.Manager()
        related_manager.remove = Mock()
        related_model1 = mock_orm.Model(pk=1, bar=11)
        related_model2 = mock_orm.Model(pk=2, bar=12)
        related_model3 = mock_orm.Model(pk=3, bar=13)
        mock_resource1 = MockResource(related_model1)
        mock_resource1.key = 1
        mock_resource2 = MockResource(related_model2)
        mock_resource2.key = 2
        mock_resource3 = MockResource(related_model3)
        mock_resource3.key = 3

        field._resource_class = Mock()
        field._resource_class.side_effect = [mock_resource1, mock_resource2, mock_resource3]
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            related_model1, related_model2, related_model3
        ))
        target_object.foos = related_manager

        ctx = mock_context()
        mock_resources = Mock()
        mock_resources.side_effect = [mock_resource1, mock_resource2]

        ctx.resolve_resource_uri = mock_resources

        field.handle_incoming(ctx, source_dict, target_object)
        related_manager.remove.assert_called_with(related_model3)

    def test_incoming_with_no_change(self):
        class MockResource(ModelResource):
            key = Mock()
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = URIListResourceField(attribute='foos', resource_class=MockResource)

        source_dict = {
            'foos': ['uri://resources/1', 'uri://resources/2']
        }

        target_object = mock_orm.Mock()
        related_manager = mock_orm.Manager()
        related_manager.remove = Mock()
        related_model1 = mock_orm.Model(pk=1, bar=11)
        related_model2 = mock_orm.Model(pk=2, bar=12)
        mock_resource1 = MockResource(related_model1)
        mock_resource1.key = 1
        mock_resource2 = MockResource(related_model2)
        mock_resource2.key = 2

        field._resource_class = Mock()
        field._resource_class.side_effect = [mock_resource1, mock_resource2]
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            related_model1, related_model2
        ))
        target_object.foos = related_manager

        ctx = mock_context()
        mock_resources = Mock()
        mock_resources.side_effect = [mock_resource1, mock_resource2]

        ctx.resolve_resource_uri = mock_resources

        field.handle_incoming(ctx, source_dict, target_object)

        related_manager.remove.assert_called_with()
        related_manager.add.assert_called_with()

    def test_outgoing(self):
        class MockResource(ModelResource):
            model_class = mock_orm.Model
            fields = [
                AttributeField(attribute='bar', type=int),
            ]

        field = URIListResourceField(attribute='foos', resource_class=MockResource)

        source_object = mock_orm.Model()
        related_manager = mock_orm.Manager()
        related_manager.all = Mock(return_value=mock_orm.QuerySet(
            mock_orm.Model(pk=1, bar=14),
            mock_orm.Model(pk=2, bar=14)
        ))

        source_object.foos = related_manager

        ctx = mock_context()
        ctx.build_resource_uri = Mock()
        ctx.build_resource_uri.side_effect = ['uri://resources/1', 'uri://resources/2']

        target_dict = {}
        field.handle_outgoing(ctx, source_object, target_dict)

        self.assertEqual(['uri://resources/1', 'uri://resources/2'], target_dict['foos'])


class StubModel(object):
    objects = None


class TestRelatedCountField(unittest.TestCase):
    @mock.patch('savory_pie.django.fields.AGGREGATE_MAPPER')
    def test_handel_outgoing_count_attr_error(self, mapper):
        ctx = mock_context()

        target_dict = {}
        mapper.get.return_value = sum
        field = RelatedCountField('name')

        count = Mock()
        count.count.return_value = 3
        query_result = Mock()
        query_result.values.return_value = count

        objects = Mock()
        objects.filter.return_value = query_result
        StubModel.objects = objects

        stub_model = StubModel()
        stub_model.id = 7

        field.handle_outgoing(ctx, stub_model, target_dict)

        self.assertEqual(
            3,
            target_dict['name'],
        )
        StubModel.objects.filter.assert_called_with(pk=7)


class TestAggregateField(unittest.TestCase):

    def _get_stub(self, query_resource, id=2):
        query_result = Mock()
        query_result.values.return_value = query_resource

        objects = Mock()
        objects.filter.return_value = query_result
        StubModel.objects = objects

        stub_model = StubModel()
        stub_model.id = id
        return stub_model

    def test_handle_outgoing_sum(self):
        ctx = mock_context()

        mock_model = Mock(name='model')
        mock_model.name__sum = 14
        target_dict = {}

        field = AggregateField('name', django.db.models.Sum)
        field.handle_outgoing(ctx, mock_model, target_dict)

        self.assertEqual(
            14,
            target_dict['name'],
        )

    @mock.patch('savory_pie.django.fields.AGGREGATE_MAPPER')
    def test_raise_unknown_method(self, mapper):
        ctx = mock_context()

        mapper.get.side_effect = AttributeError

        stub_model = self._get_stub([{'name': 23}, {'name': 10}])
        mock_sum = Mock(spec='name')
        mock_sum.name = 'sum'
        target_dict = {}

        field = AggregateField('name', mock_sum)
        with self.assertRaises(AttributeError):
            field.handle_outgoing(ctx, stub_model, target_dict)

    @mock.patch('savory_pie.django.fields.AGGREGATE_MAPPER')
    def test_handel_outgoing_sum_attr_error(self, mapper):
        ctx = mock_context()

        target_dict = {}
        mock_sum = Mock(spec='name')
        mock_sum.name = 'sum'
        mapper.get.return_value = sum
        field = AggregateField('name', mock_sum)

        stub_model = self._get_stub([{'name': 23}, {'name': 10}])
        field.handle_outgoing(ctx, stub_model, target_dict)

        self.assertEqual(
            33,
            target_dict['name'],
        )
        StubModel.objects.filter.assert_called_with(pk=2)

    @mock.patch('savory_pie.django.fields.AGGREGATE_MAPPER')
    def test_handel_outgoing_sum_non(self, mapper):
        ctx = mock_context()

        target_dict = {}
        mock_sum = Mock(spec='name')
        mock_sum.name = 'sum'
        mapper.get.return_value = sum
        field = AggregateField('name', mock_sum)

        stub_model = self._get_stub([{'name': None}])
        field.handle_outgoing(ctx, stub_model, target_dict)

        self.assertEqual(
            0,
            target_dict['name'],
        )

    def test_prepare(self):
        ctx = mock_context()
        ctx.peek.side_effect = IndexError
        related = Mock(name='related')

        field = AggregateField('name.one.two', django.db.models.Count)
        field.prepare(ctx, related)

        related.annotate.assert_called_with(
            django.db.models.Count,
            'name__one__two',
            distinct=True,
        )

    def test_prepare_not_top_level(self):
        ctx = mock_context()
        related = Mock(name='related')

        field = AggregateField('name.one.two', django.db.models.Count)

        with self.assertRaises(SavoryPieError) as cm:
            field.prepare(ctx, related)

        self.assertEqual(
            'RelatedCountField can only be used on a top level ModelResource',
            str(cm.exception)
        )

    def test_handle_outgoing(self):
        ctx = mock_context()

        mock_model = Mock(name='model')
        mock_model.name__count = 14
        target_dict = {}

        field = AggregateField('name', django.db.models.Count)
        field.handle_outgoing(ctx, mock_model, target_dict)

        self.assertEqual(
            14,
            target_dict['name'],
        )
