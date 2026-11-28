"""Show the overloads of stub methods that have no implementation."""

import griffe


class StubOverloads(griffe.Extension):
    """Expose a stub's overloads as one documented member."""

    def on_class_members(self, *, cls: griffe.Class, **kwargs: object) -> None:
        # A stub declares overloads without an implementation, which Griffe
        # keeps aside; expose them as one member carrying its overloads.
        for name, overloads in list(cls.overloads.items()):
            if not overloads or name in cls.members:
                continue
            first = overloads[0]
            function = griffe.Function(
                name,
                lineno=first.lineno,
                endlineno=overloads[-1].endlineno,
                parameters=first.parameters,
                returns=first.returns,
                docstring=next((o.docstring for o in overloads if o.docstring), None),
                parent=cls,
            )
            function.overloads = overloads
            cls.set_member(name, function)
            del cls.overloads[name]
