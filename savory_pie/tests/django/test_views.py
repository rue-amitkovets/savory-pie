import unittest
try:
    import ujson as json
except ImportError:
    from warnings import warn
    warn('Using plain JSON instead of uJSON, performance may be degraded.')
    import json
from datetime import datetime

import mock
from mock import Mock, patch
from savory_pie.errors import AuthorizationError, PreConditionError
from savory_pie.formatters import JSONFormatter
from savory_pie.resources import _ParamsImpl
from savory_pie.helpers import get_sha1
from savory_pie.django import validators
from savory_pie.tests.django.mock_request import savory_dispatch, savory_dispatch_batch
from savory_pie.tests.mock_context import mock_context


def mock_resource(name=None, resource_path=None, child_resource=None, base_regex=None):
    resource = Mock(name=name, spec=['set_base_regex'])
    resource.resource_path = resource_path
    resource.return_on_post = False

    resource.allowed_methods = set()
    resource.get = Mock(name='get')
    resource.post = Mock(name='post')
    resource.put = Mock(name='put')
    resource.delete = Mock(name='delete')
    resource.base_regex = base_regex

    resource.get_child_resource = Mock(return_value=child_resource)

    return resource


def call_args_sans_context(mock):
    return list(mock.call_args[0][1:])


class BatchViewTest(unittest.TestCase):

    def _generate_batch_partial(self, method, uri, body):
        return {
            "method": method, "uri": uri, "body": body
        }

    def create_root_resource_with_children(self, base_regex, methods=frozenset(), result=frozenset()):
        grand_child_resource = mock_resource(name='grandchild')
        child_resource = mock_resource(name='child', child_resource=grand_child_resource)

        for method in methods:
            grand_child_resource.allowed_methods.add(method)
            child_resource.allowed_methods.add(method)

        child_resource.get = Mock(return_value=result)
        child_resource.put = Mock(return_value=result)
        child_resource.post = Mock(return_value=result)

        grand_child_resource.get = Mock(return_value=result)
        grand_child_resource.put = Mock(return_value=result)
        grand_child_resource.post = Mock(return_value=result)

        root_resource = mock_resource(name='root', child_resource=child_resource, base_regex=base_regex)

        return root_resource

    def test_no_post_root_resource(self):
        root_resource = self.create_root_resource_with_children(
            r'^api/v2/(?P<base_resource>.*)$',
            methods=['GET'],
            result={'name': 'value'}
        )
        request_data = {
            "data": [{"method": "get", "uri": "someurl", "body": {}}]
        }
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='GET',
            body=json.dumps(request_data)
        )

        self.assertEqual(response.status_code, 405)

    def test_put_nocontent_batch(self):
        root_resource = self.create_root_resource_with_children(
            r'^api/v2/(?P<base_resource>.*)$',
            methods=['PUT'],
            result={}
        )
        request_data = {
            "data": [
                self._generate_batch_partial(
                    'put',
                    'http://localhost:8081/api/v2/child/grandchild',
                    {'business_id': 12345}
                )
            ]
        }
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        response_json = json.loads(response.content)
        data = response_json['data']

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 204)
        self.assertEqual(data[0]['uri'], 'http://localhost:8081/api/v2/child/grandchild')
        self.assertTrue('data' not in data[0])

    def test_put_batch(self):
        root_resource = self.create_root_resource_with_children(
            r'^api/v2/(?P<base_resource>.*)$',
            methods=['PUT'],
            result={'name': 'value'}
        )
        request_data = {
            "data": [
                self._generate_batch_partial(
                    'put',
                    'http://localhost:8081/api/v2/child/grandchild',
                    {'business_id': 12345}
                )
            ]
        }
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        response_json = json.loads(response.content)
        data = response_json['data']

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 200)
        self.assertEqual(data[0]['uri'], 'http://localhost:8081/api/v2/child/grandchild')
        self.assertEqual(data[0]['data'], {u'name': u'value'})

    def test_put_precondition_batch(self):
        root_resource = mock_resource(
            name='root',
            base_regex=r'^api/v2/(?P<base_resource>.*)$'
        )

        root_resource.allowed_methods.add('PUT')

        root_resource.get.side_effect = PreConditionError

        request_data = {
            "data": [
                self._generate_batch_partial(
                    'put',
                    'http://localhost:8081/api/v2/',
                    {'business_id': 12345}
                )
            ]
        }
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 412)

    def test_put_key_error_batch(self):
        root_resource = mock_resource(
            name='root',
            base_regex=r'^api/v2/(?P<base_resource>.*)$'
        )

        root_resource.allowed_methods.add('PUT')

        root_resource.get.side_effect = KeyError('bad key message')

        request_data = {
            "data": [
                self._generate_batch_partial(
                    'put',
                    'http://localhost:8081/api/v2/',
                    {'business_id': 12345}
                )
            ]
        }
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 400)
        self.assertEqual(data[0]['validation_errors'], {'missingData': 'bad key message'})

    def test_get_batch(self):
        root_resource = self.create_root_resource_with_children(
            r'^api/v2/(?P<base_resource>.*)$',
            methods=['GET'],
            result={'name': 'value'}
        )
        request_data = {
            "data": [
                self._generate_batch_partial(
                    'get',
                    'http://localhost:8081/api/v2/child/grandchild',
                    {'business_id': 12345}
                )
            ]
        }
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        response_json = json.loads(response.content)
        data = response_json['data']

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 200)
        self.assertEqual(data[0]['uri'], 'http://localhost:8081/api/v2/child/grandchild')
        self.assertEqual(data[0]['data'], {u'name': u'value'})

        ctx = mock_context()
        ctx.formatter = JSONFormatter()

        self.assertEqual(data[0]['etag'], get_sha1(ctx, {u'name': u'value'}))

    def test_post_batch(self):
        result = Mock(resource_path='grand_child_path')
        root_resource = self.create_root_resource_with_children(
            r'^api/v2/(?P<base_resource>.*)$',
            methods=['POST'],
            result=result
        )
        request_data = {
            "data": [
                self._generate_batch_partial('post', 'http://localhost:8081/api/v2/child/grandchild', {})
            ]
        }
        body = json.dumps(request_data)
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=body
        )

        self.assertEqual(response.status_code, 200)

        response_json = json.loads(response.content)

        data = response_json['data']

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 201)
        self.assertEqual(data[0]['uri'], 'http://localhost:8081/api/v2/child/grandchild')
        self.assertEqual(data[0]['location'], 'http://localhost:8081/api/v2/grand_child_path')

    @patch('traceback.format_exc')
    def test_exception_in_batch(self, format_exc):
        format_exc.return_value = 'some traceback'
        root_resource = mock_resource(
            name='root',
            base_regex=r'^api/v2/(?P<base_resource>.*)$'
        )

        root_resource.allowed_methods.add('GET')
        root_resource.allowed_methods.add('POST')

        root_resource.get.side_effect = Exception

        request_data = {
            "data": [
                self._generate_batch_partial('get', 'http://localhost:8081/api/v2/', {'business_id': 12345})
            ]
        }
        body = json.dumps(request_data)
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=body
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 500)
        self.assertEqual(data[0]['data'], {'error': 'some traceback'})

    def test_unauthorized_batch(self):
        child_resource = mock_resource(name='child')
        root_resource = mock_resource(
            name='root',
            child_resource=child_resource,
            base_regex=r'^api/v2/(?P<base_resource>.*)$'
        )
        child_resource.allowed_methods.add('GET')
        child_resource.get.side_effect = AuthorizationError('foo')

        request_data = {
            "data": [
                self._generate_batch_partial('get', 'http://localhost:8081/api/v2/child', {'business_id': 12345})
            ]
        }
        body = json.dumps(request_data)
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=body
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)['data']

        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 403)
        self.assertEqual(data[0]['validation_errors'], [u'Modification of field foo not authorized'])

    def test_method_not_allowed(self):
        root_resource = mock_resource(
            name='root',
            base_regex=r'^api/v2/(?P<base_resource>.*)$'
        )

        root_resource.allowed_methods.add('POST')

        root_resource.get.side_effect = Exception

        request_data = {
            "data": [
                self._generate_batch_partial('get', 'http://localhost:8081/api/v2/', {'business_id': 12345})
            ]
        }
        body = json.dumps(request_data)
        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=body
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 405)
        self.assertEqual(data[0]['allowed'], 'POST')

    def test_validation_exception_batch(self):
        root_resource = mock_resource(
            name='root',
            base_regex=r'^api/v2/(?P<base_resource>.*)$'
        )

        root_resource.allowed_methods.add('POST')

        root_resource.post.side_effect = validators.ValidationError(
            Mock(),
            {
                'class.field': 'broken',
            }
        )

        request_data = {
            "data": [
                self._generate_batch_partial(
                    'post',
                    'http://localhost:8081/api/v2/',
                    {'business_id': 12345}
                )
            ]
        }

        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)['data']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['status'], 400)
        self.assertEqual(data[0]['validation_errors'], {'class.field': 'broken'})

    def test_post_with_collision_two_batch(self):
        def side_effect(*args, **kwargs):
            # This could occur if a slightly earlier POST or PUT still had
            # the database locked during a DB transaction.
            from django.db.transaction import TransactionManagementError

            raise TransactionManagementError()

        child_resource = mock_resource(name='child')
        root_resource = mock_resource(
            name='root',
            child_resource=child_resource,
            base_regex=r'^api/v2/(?P<base_resource>.*)$'
        )
        child_resource.allowed_methods.add('POST')
        child_resource.get.side_effect = AuthorizationError('foo')
        child_resource.post = side_effect

        request_data = {
            "data": [
                self._generate_batch_partial('post', 'http://localhost:8081/api/v2/child', {'id ': 12345})
            ]
        }

        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )

        data = json.loads(response.content)['data']
        self.assertEqual(len(data), 1)

        self.assertEqual(data[0]['status'], 409)
        self.assertEqual(data[0]['uri'], 'http://localhost:8081/api/v2/child')

    @patch('savory_pie.django.views.APIContext.build_resource_uri')
    def test_post_get_put(self, build_resource_uri):
        build_resource_uri.return_value = 'some new location'
        root_resource = self.create_root_resource_with_children(
            r'^api/v2/(?P<base_resource>.*)$',
            methods=['PUT', 'GET', 'POST'],
            result={'name': 'value'}
        )

        request_data = {
            "data": [
                self._generate_batch_partial(
                    'put',
                    'http://localhost:8081/api/v2/child/grandchild',
                    {'business_id': 12345}
                ), self._generate_batch_partial(
                    'get',
                    'http://localhost:8081/api/v2/child',
                    {'business_id': 12345}
                ), self._generate_batch_partial(
                    'post',
                    'http://localhost:8081/api/v2/child/grandchild',
                    {'business_id': 12345}
                )
            ]
        }

        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        response_json = json.loads(response.content)
        data = response_json['data']
        self.assertEqual(len(data), 3)
        self.assertEqual(data[0]['status'], 200)
        self.assertEqual(data[0]['uri'], 'http://localhost:8081/api/v2/child/grandchild')
        self.assertEqual(data[0]['data'], {u'name': u'value'})

        self.assertEqual(data[1]['status'], 200)
        self.assertEqual(data[1]['uri'], 'http://localhost:8081/api/v2/child')
        self.assertEqual(data[1]['data'], {u'name': u'value'})
        ctx = mock_context()
        ctx.formatter = JSONFormatter()

        self.assertEqual(data[1]['etag'], get_sha1(ctx, {u'name': u'value'}))

        self.assertEqual(data[2]['status'], 201)
        self.assertEqual(data[2]['uri'], 'http://localhost:8081/api/v2/child/grandchild')
        self.assertEqual(data[2]['location'], 'some new location')

    def test_one_fails_one_passes(self):
        root_resource = self.create_root_resource_with_children(
            r'^api/v2/(?P<base_resource>.*)$',
            methods=['PUT'],
            result={'name': 'value'}
        )

        request_data = {
            "data": [
                self._generate_batch_partial(
                    'put',
                    'http://localhost:8081/api/v2/child/grandchild',
                    {'business_id': 12345}
                ), self._generate_batch_partial(
                    'get',
                    'http://localhost:8081/api/v2/child',
                    {'business_id': 12345}
                )
            ]
        }

        response = savory_dispatch_batch(
            root_resource,
            full_host='localhost:8081',
            method='POST',
            body=json.dumps(request_data)
        )
        self.assertEqual(response.status_code, 200)

        response_json = json.loads(response.content)
        data = response_json['data']

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['status'], 200)
        self.assertEqual(data[1]['status'], 405)


class ViewTest(unittest.TestCase):
    def test_unauthorized(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('PUT')
        root_resource.put.side_effect = AuthorizationError('foo')

        response = savory_dispatch(root_resource, method='PUT', body='{"foo": "bar"}')
        response_json = json.loads(response.content)

        self.assertIn('validation_errors', response_json)
        self.assertEqual(response_json['validation_errors'], ['Modification of field foo not authorized'])
        self.assertEqual(response.status_code, 403)

    def test_get_success(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('GET')
        root_resource.get = Mock(return_value={'foo': 'bar'})

        response = savory_dispatch(root_resource, method='GET')

        self.assertEqual(response.content, '{"foo": "bar"}')
        self.assertTrue(root_resource.get.called)
        self.assertIsNotNone(root_resource.get.call_args_list[0].request)

    def test_get_success_streaming(self):
        def get(ctx, params):
            ctx.streaming_response = True
            ctx.formatter = Mock()
            ctx.formatter.write_to = lambda *args: None
            return iter([
                '{"foo": ',
                '"bar"',
                '}',
            ])

        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('GET')
        root_resource.get = Mock(side_effect=get)

        response = savory_dispatch(root_resource, method='GET')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(''.join(response.streaming_content), '{"foo": "bar"}')
        self.assertTrue(root_resource.get.called)
        self.assertIsNotNone(root_resource.get.call_args_list[0].request)

    def test_get_not_supported(self):
        root_resource = mock_resource(name='root')

        response = savory_dispatch(root_resource, method='GET')
        self.assertEqual(response.status_code, 405)

    def test_put_no_content_success(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('PUT')
        root_resource.get.return_value = {}
        root_resource.put.return_value = None

        response = savory_dispatch(root_resource, method='PUT', body='{"foo": "bar"}')

        self.assertTrue(
            call_args_sans_context(root_resource.put),
            [
                {
                    'foo': 'bar'
                }
            ]
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, '')
        self.assertIsNotNone(root_resource.put.call_args_list[0].request)

    def test_put_content_success(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('PUT')
        root_resource.get.return_value = {}
        root_resource.put.return_value = {'key': 'value'}

        response = savory_dispatch(root_resource, method='PUT', body='{"foo": "bar"}')

        self.assertTrue(
            call_args_sans_context(root_resource.put),
            [
                {
                    'foo': 'bar'
                }
            ]
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, '{"key": "value"}')
        self.assertIsNotNone(root_resource.put.call_args_list[0].request)

    def test_put_not_supported(self):
        root_resource = mock_resource(name='root')

        response = savory_dispatch(root_resource, method='PUT', body='{}')
        self.assertEqual(response.status_code, 405)

    def test_post_success(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('POST')

        new_resource = mock_resource(name='new', resource_path='foo')
        root_resource.post = Mock(return_value=new_resource)

        response = savory_dispatch(root_resource, method='POST', body='{"foo": "bar"}')

        self.assertTrue(
            call_args_sans_context(root_resource.post),
            [
                {
                    'foo': 'bar'
                }
            ]
        )
        self.assertEqual(response['Location'], 'http://localhost/api/foo')
        self.assertIsNotNone(root_resource.post.call_args_list[0].request)

    def test_post_success_returns_resource_when_indicated(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('POST')
        root_resource.return_on_post = True
        root_resource.post.return_value = {'key': 'value'}

        response = savory_dispatch(root_resource, method='POST', body='{"foo": "bar"}')

        self.assertTrue(
            call_args_sans_context(root_resource.post),
            [
                {
                    'foo': 'bar'
                }
            ]
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.content, '{"key": "value"}')
        self.assertIsNotNone(root_resource.post.call_args_list[0].request)

    def test_post_with_collision_one(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('POST')

        def side_effect(*args):
            # This could occur if a slightly earlier POST or PUT still had
            # the database locked during a DB transaction.
            from django.db.transaction import TransactionManagementError

            raise TransactionManagementError()

        root_resource.post = Mock(side_effect=side_effect)

        response = savory_dispatch(root_resource, method='POST', body='{}')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.content, '{"resource": "http://localhost/api/"}')

    def test_post_with_collision_two(self):
        def side_effect(*args, **kwargs):
            # This could occur if a slightly earlier POST or PUT still had
            # the database locked during a DB transaction.
            from django.db.transaction import TransactionManagementError

            raise TransactionManagementError()

        root_resource = mock_resource(name='root')
        new_resource = mock_resource(name='new', resource_path='foo')
        root_resource.post = Mock(return_value=new_resource)
        root_resource.post.side_effect = side_effect
        root_resource.allowed_methods.add('POST')

        response = savory_dispatch(root_resource, method='POST', body='{}')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.content, '{"resource": "http://localhost/api/"}')

    @mock.patch('savory_pie.django.views.logger')
    def test_post_with_exception(self, logger):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('POST')

        def side_effect(*args):
            raise Exception('Some kind of server error')

        root_resource.post = Mock(side_effect=side_effect)

        response = savory_dispatch(root_resource, method='POST', body='{}')
        self.assertEqual(response.status_code, 500)
        content = json.loads(response.content)
        self.assertTrue('error' in content)
        self.assertTrue(content['error'].startswith('Traceback (most recent call last):'))
        self.assertTrue('Some kind of server error' in content['error'])
        self.assertTrue(logger.exception.called)

    def test_post_not_supported(self):
        root_resource = mock_resource(name='root')

        response = savory_dispatch(root_resource, method='POST', body='{}')

        self.assertEqual(response.status_code, 405)

    def test_delete_success(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('DELETE')

        savory_dispatch(root_resource, method='DELETE')
        self.assertTrue(root_resource.delete.called)
        self.assertIsNotNone(root_resource.delete.call_args_list[0].request)

    def test_delete_not_supported(self):
        root_resource = mock_resource(name='root')

        response = savory_dispatch(root_resource, method='DELETE')
        self.assertEqual(response.status_code, 405)

    def test_child_resolution(self):
        child_resource = mock_resource(name='child')
        child_resource.allowed_methods.add('GET')
        child_resource.get = Mock(return_value={})

        root_resource = mock_resource(name='root', child_resource=child_resource)

        savory_dispatch(root_resource, method='GET', resource_path='child')

        self.assertEqual(call_args_sans_context(root_resource.get_child_resource), ['child'])
        self.assertTrue(child_resource.get.called)
        self.assertIsNotNone(child_resource.get.call_args_list[0].request)

    def test_grandchild_resolution(self):
        grand_child_resource = mock_resource(name='grandchild')
        grand_child_resource.allowed_methods.add('GET')
        grand_child_resource.get = Mock(return_value={})

        child_resource = mock_resource(name='child', child_resource=grand_child_resource)

        root_resource = mock_resource(name='root', child_resource=child_resource)

        savory_dispatch(root_resource, method='GET', resource_path='child/grandchild')

        self.assertEqual(call_args_sans_context(root_resource.get_child_resource), ['child'])
        self.assertEqual(call_args_sans_context(child_resource.get_child_resource), ['grandchild'])
        self.assertTrue(grand_child_resource.get.called)
        self.assertIsNotNone(grand_child_resource.get.call_args_list[0].request)

    def test_child_resolution_fail(self):
        root_resource = mock_resource(name='root')

        response = savory_dispatch(root_resource, method='GET', resource_path='child/grandchild')
        self.assertEqual(response.status_code, 404)

    def test_exception_handling(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('GET')
        root_resource.get.side_effect = Exception('Fail')

        response = savory_dispatch(root_resource, method='GET')

        response_json = json.loads(response.content)
        self.assertIn('error', response_json)
        self.assertEqual(response.status_code, 500)

    def test_validation_handling(self):
        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('PUT')
        root_resource.put.side_effect = validators.ValidationError(
            Mock(),
            {
                'class.field': 'broken',
            }
        )

        response = savory_dispatch(root_resource, method='PUT', body='{}')

        response_json = json.loads(response.content)
        self.assertIn('validation_errors', response_json)
        self.assertEqual(response_json['validation_errors']['class.field'], 'broken')
        self.assertEqual(response.status_code, 400)

    def test_set_header(self):
        """
        Tests the set_header method in the APIContext class
        """

        def get(ctx, params):
            ctx.set_header('foo1', 'bar1')
            return {'foo2': 'bar2'}

        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('GET')
        root_resource.get = get

        response = savory_dispatch(root_resource, method='GET')

        self.assertEqual(response['foo1'], 'bar1')
        self.assertEqual(response.content, '{"foo2": "bar2"}')

    def test_set_expires(self):
        expires = datetime(2005, 7, 14, 12, 30)

        def get(ctx, params):
            ctx.set_expires_header(datetime.utcnow())
            ctx.set_expires_header(expires)
            ctx.set_expires_header(datetime.utcnow())
            return {'foo2': 'bar2'}

        root_resource = mock_resource(name='root')
        root_resource.allowed_methods.add('GET')
        root_resource.get = get

        response = savory_dispatch(root_resource, method='GET')

        self.assertEqual(response['Expires'], expires.isoformat('T'))
        self.assertEqual(response.content, '{"foo2": "bar2"}')


class HashTestCase(unittest.TestCase):
    def test_mutable_parameters(self):
        dct = {'a': 'http://one/two/three/four'}
        ctx = mock_context()
        ctx.formatter = JSONFormatter()

        get_sha1(ctx, dct)
        # Make sure that the dct that we pass in is the same dict that gets returned
        self.assertEqual(dct, {'a': 'http://one/two/three/four'})

    def test_has_dictionary(self):
        dct = {'a': 'b', 'c': 'd'}
        ctx = mock_context()
        ctx.formatter = JSONFormatter()
        self.assertEqual(get_sha1(ctx, dct), '855e751b12bf88bce273d5e1d93a31af9e4945d6')


class DjangoFPramsTest(unittest.TestCase):
    def test_get_list(self):
        get = Mock(name='mock')
        get.getlist.return_value = ['bar', 'baz']
        params = _ParamsImpl(get)

        result = params.get_list('foo')

        self.assertEqual(result, ['bar', 'baz'])
        get.getlist.assert_called_with('foo')
