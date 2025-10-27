from dataclasses import asdict, fields, is_dataclass
from typing import Any, Type, TypeVar, Dict

T = TypeVar("T")


def to_json(obj: Any) -> Dict[str, Any]:
    return asdict(obj)


def from_json(cls: Type[T], data: Any) -> T:
    kwargs = {}
    for f in fields(cls):
        value = data.get(f.name)
        if value is None:
            kwargs[f.name] = None
            continue

        ftype = f.type
        origin = getattr(ftype, "__origin__", None)

        if origin is list:
            subtype = ftype.__args__[0]
            kwargs[f.name] = [from_json(subtype, i) for i in value]

        elif is_dataclass(ftype):
            kwargs[f.name] = from_json(ftype, value)
        else:
            kwargs[f.name] = value

    return cls(**kwargs)
