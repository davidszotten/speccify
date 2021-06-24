import json
import types
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

import pytest
from django.test.client import RequestFactory
from django.urls import path
from drf_spectacular.views import SpectacularAPIView
from rest_framework.request import Request

from speccify.decorator import QueryParams, RequestData, api_view


@dataclass
class Person(QueryParams):
    name: str


@dataclass
class Display:
    length: str


def _get_schema(urlpatterns):
    rf = RequestFactory()

    urlconf = types.ModuleType("urlconf")
    urlconf.urlpatterns = urlpatterns

    schema_view = SpectacularAPIView.as_view(urlconf=urlpatterns)
    schema_request = rf.get("schema")
    schema_response = schema_view(request=schema_request, format="json")

    schema_response.render()
    schema = json.loads(schema_response.content.decode())
    return schema


def test_basic(rf):
    @api_view(
        methods=["GET"],
        permissions=[],
    )
    def view(request: Request, person: Person) -> Display:
        length = len(person.name)
        return Display(length=str(length))

    request = rf.get("/?name=value")
    response = view(request)
    assert response.data == {"length": "5"}


def test_schema(rf):
    @dataclass
    class Child1:
        c1: str

    @dataclass
    class Child2:
        c1: str

    @dataclass
    class Parent(RequestData):
        child1: Child1
        child2: Child2

    @api_view(
        methods=["POST"],
        permissions=[],
    )
    def view(request: Request, person: Parent) -> None:
        pass

    urlpatterns = [
        path("view", view),
    ]
    schema = _get_schema(urlpatterns)
    paths = schema["paths"]
    assert "/view" in paths
    assert "post" in paths["/view"]

    assert "Child1" in schema["components"]["schemas"]


@dataclass
class MyQueryData(QueryParams):
    q: str


@dataclass
class MyDefaultQueryData(QueryParams):
    q: Optional[str] = "foo"


@dataclass
class MyRequestData(RequestData):
    d: str


@dataclass
class MyResponse:
    r: str


@dataclass
class MyDefaultResponse:
    r: Optional[str] = None


def test_query_params(rf):
    @api_view(methods=["GET"], permissions=[])
    def view(request: Request, my_query: MyQueryData) -> MyResponse:
        foo = my_query.q
        bar = len(foo)
        return MyResponse(r=bar)

    request = rf.get("/?q=value")
    response = view(request)
    assert response.data == {"r": "5"}


def test_extra_query_params(rf):
    @api_view(methods=["GET"], permissions=[])
    def view(request: Request, my_query: MyQueryData) -> None:
        assert not hasattr(my_query, "r")
        return

    request = rf.get("/?q=value&r=foo")
    response = view(request)
    assert response.status_code == 200


def test_default_query_params(rf):
    @api_view(methods=["GET"], permissions=[])
    def view(request: Request, my_query: MyDefaultQueryData) -> None:
        return

    request = rf.get("/")
    response = view(request)
    assert response.status_code == 200


def test_default_response_key(rf):
    @api_view(methods=["GET"], permissions=[])
    def view(request: Request) -> MyDefaultResponse:
        return MyDefaultResponse()

    request = rf.get("/")
    response = view(request)
    assert response.data == {"r": None}


def test_raise_type_error_if_optional_not_provided():
    @dataclass
    class OptionalWithoutDefault(QueryParams):
        q: Optional[str]

    def view(request: Request, my_query: OptionalWithoutDefault) -> None:
        return None

    with pytest.raises(TypeError) as exc_info:
        api_view(methods=["GET"], permissions=[])(view)

    assert "Optional fields must provide a default" in str(exc_info.value)
    assert "OptionalWithoutDefault'>.q`." in str(exc_info.value)


def test_post_data(rf):
    @api_view(
        methods=["POST"],
        permissions=[],
    )
    def view(request: Request, my_data: MyRequestData) -> MyResponse:
        foo = my_data.d
        bar = len(foo)
        return MyResponse(r=bar)

    request = rf.post("/", {"d": "value"})
    response = view(request)
    assert response.data == {"r": "5"}


def test_urlencoded_request_data(rf):
    @dataclass
    class MyData(RequestData):
        foo: str

    @api_view(
        methods=["PUT"],
        permissions=[],
    )
    def view(request: Request, my_query: MyData) -> None:
        assert my_query.foo == "bar"

    request = rf.put(
        "/foo", urlencode({"foo": "bar"}), "application/x-www-form-urlencoded"
    )

    response = view(request)
    assert response.status_code == 200


def test_disallows_multiple_query_param_arguments():
    @dataclass
    class D1(QueryParams):
        foo: str

    class D2(QueryParams):
        bar: str

    with pytest.raises(TypeError) as exc_info:

        @api_view(
            methods=["GET"],
            permissions=[],
        )
        def view(request: Request, d1: D1, d2: D2) -> None:
            pass

    assert "At most one " in str(exc_info.value)


def test_stacking(rf):
    @dataclass
    class MyQueryData(QueryParams):
        q: str

    @dataclass
    class MyRequestData(RequestData):
        d: str

    @dataclass
    class MyResponse:
        r: str

    @api_view(methods=["GET"], permissions=[])
    def view_single(request: Request, my_data: MyQueryData) -> MyResponse:
        pass

    @api_view(methods=["GET"], permissions=[])
    def view_get(request: Request, my_data: MyQueryData) -> MyResponse:
        return MyResponse(r="get")

    @view_get.add(methods=["POST"])
    def view_post(request: Request, my_data: MyRequestData) -> MyResponse:
        return MyResponse(r="post")

    get_request = rf.get("/?q=value")
    get_response = view_get(get_request)
    get_response.render()
    assert get_response.data == {"r": "get"}

    post_request = rf.post("/", data={"d": "value"})
    post_response = view_get(post_request)
    assert post_response.data == {"r": "post"}

    with pytest.raises(TypeError):
        # should not be possible to mount this one
        path("bad", view_post)

    urlpatterns = [
        path("single", view_single),
        path("multiple", view_get),
    ]
    schema = _get_schema(urlpatterns)

    paths = schema["paths"]
    assert "/single" in paths
    assert "get" in paths["/single"]

    assert "/multiple" in paths
    assert "get" in paths["/multiple"]
    assert "post" in paths["/multiple"]
