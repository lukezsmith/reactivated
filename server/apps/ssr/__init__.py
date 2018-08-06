from django import forms
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token

from typing import Any, Dict, Tuple, Union, Sequence, Mapping, TypeVar, Callable, Type, overload, Optional, cast, List, NamedTuple

from mypy_extensions import TypedDict, Arg, KwArg

import abc
import simplejson


type_registry: Dict[str, Tuple] = {}


Serializable = Tuple[
    Union[
        str,
        bool,
        Dict[str, Union[str, int, float, bool, None]],
        Sequence[
            Tuple[
                Union[
                    str,
                    bool,
                    int,
                    Dict[str, Union[str, int, float, bool, None]],
                ],
                ...
            ]
        ],

        Tuple[
            Union[
                str,
                int,
                float,
                bool,

                Sequence[
                    Tuple[
                        Union[
                            str,
                            int,
                            float,
                            bool,
                            'TypeHint',
                        ],
                        ...
                    ]
                ],

                Mapping[str, Union[
                    str,
                    int,
                    float,
                    bool,
                    Sequence[str],
                    None
                ]],
                'TypeHint',
            ],
            ...
        ]
    ],
    ...
]


K = TypeVar('K')
P = TypeVar('P', bound=Serializable)

View = Callable[[HttpRequest, K], Union[P, HttpResponse]]
NoArgsView = Callable[[HttpRequest], Union[P, HttpResponse]]


def to_camel_case(snake_str: str) -> str:
    components = snake_str.split('_')
    return ''.join(x.title() for x in components)


    reveal_type(form_view)


class Message(NamedTuple):
    level: int
    level_tag: str
    message: str


class JSXResponse:
    def __init__(self, *, csrf_token: str, template_name: str, props: P, messages: List[Message]) -> None:

        self.props = {
            'csrf_token': csrf_token,
            'template_name': template_name,
            'messages': messages,
            **(props if isinstance(props, dict) else props._asdict()),  # type: ignore
        }

    def as_json(self) -> Any:
        return simplejson.dumps(self.props)


def render_jsx(request: HttpRequest, template_name: str, props: Union[P, HttpResponse]) -> HttpResponse:
    if isinstance(props, HttpResponse):
        return props


    current_messages = messages.get_messages(request)

    response = JSXResponse(
        template_name=template_name,
        csrf_token=get_token(request),
        messages=[
            Message(
                level=m.level,
                level_tag=m.level_tag,
                message=m.message,
            ) for m in current_messages
        ],
        props=props,
    )
    return HttpResponse(response.as_json(), content_type='application/ssr+json')


@overload
def ssr(*,
        props: Type[P],
        params: None = None) -> Callable[[NoArgsView[P]], Callable[[Arg(HttpRequest, 'request'), KwArg(Any)], HttpResponse]]: ...


@overload
def ssr(*,
        props: Type[P],
        params: Type[K]) -> Callable[[View[K, P]], Callable[[Arg(HttpRequest, 'request'), KwArg(Any)], HttpResponse]]: ...


def ssr(*,
        props: Type[P],
        params: Optional[Type[K]] = None) -> Union[
                                                 Callable[[NoArgsView[P]], Callable[[Arg(HttpRequest, 'request'), KwArg(Any)], HttpResponse]],
                                                 Callable[[View[K, P]], Callable[[Arg(HttpRequest, 'request'), KwArg(Any)], HttpResponse]],
                                             ]:
    type_registry[props.__name__] = props  # type: ignore

    def no_args_wrap_with_jsx(original: NoArgsView[P]) -> Callable[[Arg(HttpRequest, 'request'), KwArg(Any)], HttpResponse]:
        def wrapper(request: HttpRequest, **kwargs: Any) -> HttpResponse:
            props = original(request)
            template_name = to_camel_case(original.__name__)

            return render_jsx(request, template_name, props)

        return wrapper

    def wrap_with_jsx(original: View[K, P]) -> Callable[[Arg(HttpRequest, 'request'), KwArg(Any)], HttpResponse]:
        def wrapper(request: HttpRequest, **kwargs: Any) -> HttpResponse:
            props = original(request, cast(Any, params)(**kwargs))
            template_name = to_camel_case(original.__name__)

            return render_jsx(request, template_name, props)
        return wrapper

    if params is None:
        return no_args_wrap_with_jsx
    else:
        return wrap_with_jsx


class TypeHint(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str:
        pass


def create_schema(Type: Any) -> Any:
    if (getattr(Type, '__origin__', None) == Union or
        str(Type.__class__) == 'typing.Union'):  # TODO: find a better way to do this.
        return {
            'anyOf': [
                create_schema(field) for field in Type.__args__
            ],
        }
    elif str(Type.__class__) == 'typing.Any':  # TODO: find a better way to do this.
        return {
        }
    elif getattr(Type, '_name', None) == 'Dict':
        return {
            'type': 'object',
            'additionalProperties': create_schema(Type.__args__[1]),
        }
    elif getattr(Type, '_name', None) == 'List':
        return {
            'type': 'array',
            'items': create_schema(Type.__args__[0]),
        }
    elif issubclass(Type, List):
        return {
            'type': 'array',
            'items': create_schema(Type.__args__[0]),
        }
    elif issubclass(Type, Dict):
        return {
            'type': 'object',
            'additionalProperties': create_schema(Type.__args__[1]),
        }
    elif issubclass(Type, bool):
        return {
            'type': 'bool',
        }
    elif issubclass(Type, int):
        return {
            'type': 'number',
        }
    elif issubclass(Type, str):
        return {
            'type': 'string',
        }
    elif Type is type(None):
        return {
            'type': 'null',
        }
    elif hasattr(Type, '_asdict'):
        required = []
        properties = {}

        for field_name, SubType in Type.__annotations__.items():
            field_schema = create_schema(SubType)

            if field_schema is not None:

                required.append(field_name)
                properties[field_name] = field_schema

        return {
            'title': Type.__name__,
            'type': 'object',
            'additionalProperties': False,
            'properties': properties,
            'required': required,
        }
    elif issubclass(Type, TypeHint):
        return None
        """
            return {
                'title': Type().name,
                'type': 'object',
                'additionalProperties': False,
           }
        """
    assert False


def wrap_with_globals(props: Any) -> Any:
    return {
        **props,
        'properties': {
            **props['properties'],
            'template_name': {'type': 'string'},
            'csrf_token': {'type': 'string'},
            'messages': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'level': {
                            'type': 'number',
                        },
                        'level_tag': {
                            'type': 'string',
                        },
                        'message': {
                            'type': 'string',
                        },
                    },
                    'required': [
                        'level',
                        'level_tag',
                        'message',
                    ],
                    'additionalProperties': False,
                },
            },
        },
        'required': [
            *props['required'],
            'template_name',
            'csrf_token',
            'messages',
        ],
    }


def generate_schema() -> str:
    schema = {
        'title': 'Schema',
        'type': 'object',
        'properties': {
            name: wrap_with_globals(create_schema(Props))
            for name, Props in type_registry.items()
        },
        'additionalProperties': False,
        'required': [name for name in type_registry.keys()],
    }

    return simplejson.dumps(schema, indent=4)


class WidgetType(TypeHint):
    name = 'WidgetType'


class FieldType(NamedTuple):
    name: str
    label: str
    widget: WidgetType


class FormType(NamedTuple):
    errors: Dict[str, Optional[List[str]]]
    fields: List[FieldType]


class SSRFormRenderer:
    def render(self, template_name, context, request=None):
        return simplejson.dumps(context)


def serialize_form(form: Optional[forms.BaseForm]) -> Optional[FormType]:
    if form is None:
        return None

    form.renderer = SSRFormRenderer()

    return FormType(
        errors=form.errors,
        fields=[
            FieldType(
                widget=simplejson.loads(str(field))['widget'],
                name=field.name,
                label=str(field.label), # This can be a lazy proxy, so we must call str on it.
            ) for field in form
        ],
   )
