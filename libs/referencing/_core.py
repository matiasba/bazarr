from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import (
    Any,
    Callable,
    ClassVar,
    Generic,
    Protocol,
    Tuple,
    TypeVar,
    cast,
)
from urllib.parse import unquote, urldefrag, urljoin

from attrs import evolve, field
from pyrsistent import PMap as PMapType, plist, pmap, pset
from pyrsistent.typing import PList, PMap, PSet

from referencing import exceptions
from referencing._attrs import frozen
from referencing.typing import URI, Anchor as AnchorType, D, Mapping, Retrieve

EMPTY_RESOURCES: PMap[URI, Resource[Any]] = pmap({}, pre_size=64)
EMPTY_ANCHORS = cast(PMap[Tuple[URI, str], AnchorType[Any]], EMPTY_RESOURCES)
EMPTY_UNCRAWLED: PSet[URI] = pset(pre_size=128)
EMPTY_PREVIOUS_RESOLVERS: PList[URI] = plist()


class _MaybeInSubresource(Protocol[D]):
    def __call__(
        self,
        segments: Sequence[int | str],
        resolver: Resolver[D],
        subresource: Resource[D],
    ) -> Resolver[D]:
        ...


@frozen
class Specification(Generic[D]):
    """
    A specification which defines referencing behavior.

    The various methods of a `Specification` allow for varying referencing
    behavior across JSON Schema specification versions, etc.
    """

    #: A short human-readable name for the specification, used for debugging.
    name: str

    #: Find the ID of a given document.
    id_of: Callable[[D], URI | None]

    #: Retrieve the subresources of the given document (without traversing into
    #: the subresources themselves).
    subresources_of: Callable[[D], Iterable[D]]

    #: While resolving a JSON pointer, conditionally enter a subresource
    #: (if e.g. we have just entered a keyword whose value is a subresource)
    maybe_in_subresource: _MaybeInSubresource[D]

    #: Retrieve the anchors contained in the given document.
    _anchors_in: Callable[
        [Specification[D], D],
        Iterable[AnchorType[D]],
    ] = field(alias="anchors_in")

    #: An opaque specification where resources have no subresources
    #: nor internal identifiers.
    OPAQUE: ClassVar[Specification[Any]]

    def __repr__(self):
        return f"<Specification name={self.name!r}>"

    def anchors_in(self, contents: D):
        """
        Retrieve the anchors contained in the given document.
        """
        return self._anchors_in(self, contents)

    def create_resource(self, contents: D) -> Resource[D]:
        """
        Create a resource which is interpreted using this specification.
        """
        return Resource(contents=contents, specification=self)


Specification.OPAQUE = Specification(
    name="opaque",
    id_of=lambda contents: None,
    subresources_of=lambda contents: [],
    anchors_in=lambda specification, contents: [],
    maybe_in_subresource=lambda segments, resolver, subresource: resolver,
)


@frozen
class Resource(Generic[D]):
    r"""
    A document (deserialized JSON) with a concrete interpretation under a spec.

    In other words, a Python object, along with an instance of `Specification`
    which describes how the document interacts with referencing -- both
    internally (how it refers to other `Resource`\ s) and externally (how it
    should be identified such that it is referenceable by other documents).
    """

    contents: D
    _specification: Specification[D] = field(alias="specification")

    @classmethod
    def from_contents(
        cls,
        contents: D,
        default_specification: Specification[D] = None,  # type: ignore[reportGeneralTypeIssues]  # noqa: E501
    ) -> Resource[D]:
        """
        Attempt to discern which specification applies to the given contents.

        Raises:

            `CannotDetermineSpecification`

                if the given contents don't have any discernible
                information which could be used to guess which
                specification they identify as
        """
        specification = default_specification
        if isinstance(contents, Mapping):
            jsonschema_dialect_id = contents.get("$schema")  # type: ignore[reportUnknownMemberType]  # noqa: E501
            if jsonschema_dialect_id is not None:
                from referencing.jsonschema import specification_with

                specification = specification_with(
                    jsonschema_dialect_id,  # type: ignore[reportUnknownArgumentType]  # noqa: E501
                    default=default_specification,
                )

        if specification is None:  # type: ignore[reportUnnecessaryComparison]
            raise exceptions.CannotDetermineSpecification(contents)
        return cls(contents=contents, specification=specification)  # type: ignore[reportUnknownArgumentType]  # noqa: E501

    @classmethod
    def opaque(cls, contents: D) -> Resource[D]:
        """
        Create an opaque `Resource` -- i.e. one with opaque specification.

        See `Specification.OPAQUE` for details.
        """
        return Specification.OPAQUE.create_resource(contents=contents)

    def id(self) -> URI | None:
        """
        Retrieve this resource's (specification-specific) identifier.
        """
        return self._specification.id_of(self.contents)

    def subresources(self) -> Iterable[Resource[D]]:
        """
        Retrieve this resource's subresources.
        """
        return (
            Resource.from_contents(
                each,
                default_specification=self._specification,
            )
            for each in self._specification.subresources_of(self.contents)
        )

    def anchors(self) -> Iterable[AnchorType[D]]:
        """
        Retrieve this resource's (specification-specific) identifier.
        """
        return self._specification.anchors_in(self.contents)

    def pointer(self, pointer: str, resolver: Resolver[D]) -> Resolved[D]:
        """
        Resolve the given JSON pointer.

        Raises:

            `exceptions.PointerToNowhere`

                if the pointer points to a location not present in the document
        """
        contents = self.contents
        segments: list[int | str] = []
        for segment in unquote(pointer[1:]).split("/"):
            if isinstance(contents, Sequence):
                segment = int(segment)
            else:
                segment = segment.replace("~1", "/").replace("~0", "~")
            try:
                contents = contents[segment]  # type: ignore[reportUnknownArgumentType]  # noqa: E501
            except LookupError:
                raise exceptions.PointerToNowhere(ref=pointer, resource=self)

            segments.append(segment)
            last = resolver
            resolver = self._specification.maybe_in_subresource(
                segments=segments,
                resolver=resolver,
                subresource=self._specification.create_resource(contents),  # type: ignore[reportUnknownArgumentType]  # noqa: E501
            )
            if resolver is not last:
                segments = []
        return Resolved(contents=contents, resolver=resolver)  # type: ignore[reportUnknownArgumentType]  # noqa: E501


def _fail_to_retrieve(uri: URI):
    raise exceptions.NoSuchResource(ref=uri)


def _to_pmap(
    value: dict[URI, Resource[D]]
    | PMap[URI, Resource[D]]
    | list[tuple[URI, Resource[D]]],
):
    return value if isinstance(value, PMapType) else pmap(value)


@frozen
class Registry(Mapping[URI, Resource[D]]):
    r"""
    A registry of `Resource`\ s, each identified by their canonical URIs.

    Registries store a collection of in-memory resources, and optionally
    enable additional resources which may be stored elsewhere (e.g. in a
    database, a separate set of files, over the network, etc.).

    They also lazily walk their known resources, looking for subresources
    within them. In other words, subresources contained within any added
    resources will be retrievable via their own IDs (though this discovery of
    subresources will be delayed until necessary).

    Registries are immutable, and their methods return new instances of the
    registry with the additional resources added to them.

    The ``retrieve`` argument can be used to configure retrieval of resources
    dynamically, either over the network, from a database, or the like.
    Pass it a callable which will be called if any URI not present in the
    registry is accessed. It must either return a `Resource` or else raise a
    `NoSuchResource` exception indicating that the resource does not exist
    even according to the retrieval logic.
    """

    _resources: PMap[URI, Resource[D]] = field(
        default=EMPTY_RESOURCES,
        converter=_to_pmap,
    )
    _anchors: PMap[tuple[URI, str], AnchorType[D]] = field(
        default=EMPTY_ANCHORS,
    )
    _uncrawled: PSet[URI] = field(default=EMPTY_UNCRAWLED)
    _retrieve: Retrieve[D] = field(default=_fail_to_retrieve)

    def __getitem__(self, uri: URI) -> Resource[D]:
        """
        Return the `Resource` identified by the given URI.
        """
        try:
            return self._resources[uri]
        except KeyError:
            raise exceptions.NoSuchResource(ref=uri)

    def __iter__(self) -> Iterator[URI]:
        """
        Iterate over all fully crawled URIs in the registry.
        """
        return iter(self._resources)

    def __len__(self) -> int:
        """
        Count the total number of fully crawled resources in this registry.
        """
        return len(self._resources)

    def __rmatmul__(self, new: Resource[D] | Iterable[Resource[D]]):
        """
        Add resource(s) to a new registry, using their internal IDs.

        Resources must have a internal IDs (e.g. the ``$id`` keyword in modern
        JSON Schema versions), otherwise an error will be raised.

        Use this via:

            * ``resource @ registry`` or

            * ``[iterable, of, multiple, resources] @ registry``

        which -- again, assuming the resources have internal IDs -- is
        equivalent to calling `Registry.with_resources` as such:

        .. code:: python

            registry.with_resources(
                (resource.id(), resource) for resource in new_resources
            )
        """
        if isinstance(new, Resource):
            new = (new,)

        resources = self._resources.evolver()
        uncrawled = self._uncrawled.evolver()
        for resource in new:
            id = resource.id()
            if id is None:
                raise exceptions.NoInternalID(resource=resource)
            uncrawled.add(id)
            resources.set(id, resource)
        return evolve(
            self,
            resources=resources.persistent(),
            uncrawled=uncrawled.persistent(),
        )

    def __repr__(self) -> str:
        size = len(self)
        pluralized = "resource" if size == 1 else "resources"
        if self._uncrawled:
            uncrawled = len(self._uncrawled)
            if uncrawled == size:
                summary = f"uncrawled {pluralized}"
            else:
                summary = f"{pluralized}, {uncrawled} uncrawled"
        else:
            summary = f"{pluralized}"
        return f"<Registry ({size} {summary})>"

    def get_or_retrieve(self, uri: URI):
        """
        Get a resource from the registry, crawling or retrieving if necessary.
        """
        resource = self._resources.get(uri)
        if resource is not None:
            return Retrieved(registry=self, value=resource)

        registry = self.crawl()
        resource = registry._resources.get(uri)
        if resource is not None:
            return Retrieved(registry=registry, value=resource)

        try:
            resource = registry._retrieve(uri)
        except (
            exceptions.CannotDetermineSpecification,
            exceptions.NoSuchResource,
        ):
            raise
        except Exception:
            raise exceptions.Unretrievable(ref=uri)
        else:
            registry = registry.with_resource(uri, resource)
            return Retrieved(registry=registry, value=resource)

    def remove(self, uri: URI):
        """
        Return a registry with the resource identified by a given URI removed.
        """
        if uri not in self._resources:
            raise exceptions.NoSuchResource(ref=uri)

        return evolve(
            self,
            resources=self._resources.remove(uri),
            uncrawled=self._uncrawled.discard(uri),
            anchors=pmap(
                (k, v) for k, v in self._anchors.items() if k[0] != uri
            ),
        )

    def anchor(self, uri: URI, name: str):
        """
        Retrieve the given anchor, which must already have been found.
        """
        value = self._anchors.get((uri, name))
        if value is not None:
            return Retrieved(value=value, registry=self)

        registry = self.crawl()
        value = registry._anchors.get((uri, name))
        if value is not None:
            return Retrieved(value=value, registry=registry)
        raise exceptions.NoSuchAnchor(ref=uri, resource=self[uri], anchor=name)

    def contents(self, uri: URI) -> D:
        """
        Retrieve the contents identified by the given URI.
        """
        return self._resources[uri].contents

    def crawl(self) -> Registry[D]:
        """
        Immediately crawl all added resources, discovering subresources.
        """
        resources = self._resources.evolver()
        anchors = self._anchors.evolver()
        uncrawled = [(uri, resources[uri]) for uri in self._uncrawled]
        while uncrawled:
            uri, resource = uncrawled.pop()

            id = resource.id()
            if id is not None:
                uri = urljoin(uri, id)
                resources[uri] = resource
            for each in resource.anchors():
                anchors.set((uri, each.name), each)
            uncrawled.extend((uri, each) for each in resource.subresources())
        return evolve(
            self,
            resources=resources.persistent(),
            anchors=anchors.persistent(),
            uncrawled=EMPTY_UNCRAWLED,
        )

    def with_resource(self, uri: URI, resource: Resource[D]):
        """
        Add the given `Resource` to the registry, without crawling it.
        """
        return self.with_resources([(uri, resource)])

    def with_resources(
        self,
        pairs: Iterable[tuple[URI, Resource[D]]],
    ) -> Registry[D]:
        r"""
        Add the given `Resource`\ s to the registry, without crawling them.
        """
        resources = self._resources.evolver()
        uncrawled = self._uncrawled.evolver()
        for uri, resource in pairs:
            uncrawled.add(uri)
            resources[uri] = resource
        return evolve(
            self,
            resources=resources.persistent(),
            uncrawled=uncrawled.persistent(),
        )

    def with_contents(
        self,
        pairs: Iterable[tuple[URI, D]],
        **kwargs: Any,
    ) -> Registry[D]:
        r"""
        Add the given contents to the registry, autodetecting when necessary.
        """
        return self.with_resources(
            (uri, Resource.from_contents(each, **kwargs))
            for uri, each in pairs
        )

    def combine(self, *registries: Registry[D]) -> Registry[D]:
        """
        Combine together one or more other registries, producing a unified one.
        """
        if registries == (self,):
            return self
        resources = self._resources
        anchors = self._anchors
        uncrawled = self._uncrawled
        retrieve = self._retrieve
        for registry in registries:
            resources = resources.update(registry._resources)  # type: ignore[reportUnknownMemberType]  # noqa: E501
            anchors = anchors.update(registry._anchors)  # type: ignore[reportUnknownMemberType]  # noqa: E501
            uncrawled = uncrawled.update(registry._uncrawled)

            if registry._retrieve is not _fail_to_retrieve:
                if registry._retrieve is not retrieve is not _fail_to_retrieve:
                    raise ValueError(
                        "Cannot combine registries with conflicting retrieval "
                        "functions.",
                    )
                retrieve = registry._retrieve
        return evolve(
            self,
            anchors=anchors,
            resources=resources,
            uncrawled=uncrawled,
            retrieve=retrieve,
        )

    def resolver(self, base_uri: URI = "") -> Resolver[D]:
        """
        Return a `Resolver` which resolves references against this registry.
        """
        return Resolver(base_uri=base_uri, registry=self)

    def resolver_with_root(self, resource: Resource[D]) -> Resolver[D]:
        """
        Return a `Resolver` with a specific root resource.
        """
        uri = resource.id() or ""
        return Resolver(
            base_uri=uri,
            registry=self.with_resource(uri, resource),
        )


T = TypeVar("T", AnchorType[Any], Resource[Any])


@frozen
class Retrieved(Generic[D, T]):
    """
    A value retrieved from a `Registry`.
    """

    value: T
    registry: Registry[D]


@frozen
class Resolved(Generic[D]):
    """
    A reference resolved to its contents by a `Resolver`.
    """

    contents: D
    resolver: Resolver[D]


@frozen
class Resolver(Generic[D]):
    """
    A reference resolver.

    Resolvers help resolve references (including relative ones) by
    pairing a fixed base URI with a `Registry`.

    References are resolved against the base URI, and the combined URI
    is then looked up within the registry.

    The process of resolving a reference may itself involve calculating
    a *new* base URI for future reference resolution (e.g. if an
    intermediate resource sets a new base URI), or may involve encountering
    additional subresources and adding them to a new registry.
    """

    _base_uri: str = field(alias="base_uri")
    _registry: Registry[D] = field(alias="registry")
    _previous: PList[URI] = field(
        default=EMPTY_PREVIOUS_RESOLVERS,
        repr=False,
        alias="previous",
    )

    def lookup(self, ref: URI) -> Resolved[D]:
        """
        Resolve the given reference to the resource it points to.

        Raises:

            `exceptions.Unresolvable`

                or a subclass thereof (see below) if the reference isn't
                resolvable

            `exceptions.NoSuchAnchor`

                if the reference is to a URI where a resource exists but
                contains a plain name fragment which does not exist within
                the resource

            `exceptions.PointerToNowhere`

                if the reference is to a URI where a resource exists but
                contains a JSON pointer to a location within the resource
                that does not exist
        """
        if ref.startswith("#"):
            uri, fragment = self._base_uri, ref[1:]
        else:
            uri, fragment = urldefrag(urljoin(self._base_uri, ref))
        try:
            retrieved = self._registry.get_or_retrieve(uri)
        except exceptions.NoSuchResource:
            raise exceptions.Unresolvable(ref=ref) from None
        except exceptions.Unretrievable:
            raise exceptions.Unresolvable(ref=ref)

        if fragment.startswith("/"):
            resolver = self._evolve(registry=retrieved.registry, base_uri=uri)
            return retrieved.value.pointer(pointer=fragment, resolver=resolver)

        if fragment:
            retrieved = retrieved.registry.anchor(uri, fragment)
            resolver = self._evolve(registry=retrieved.registry, base_uri=uri)
            return retrieved.value.resolve(resolver=resolver)

        resolver = self._evolve(registry=retrieved.registry, base_uri=uri)
        return Resolved(contents=retrieved.value.contents, resolver=resolver)

    def in_subresource(self, subresource: Resource[D]) -> Resolver[D]:
        """
        Create a resolver for a subresource (which may have a new base URI).
        """
        id = subresource.id()
        if id is None:
            return self
        return evolve(self, base_uri=urljoin(self._base_uri, id))

    def dynamic_scope(self) -> Iterable[tuple[URI, Registry[D]]]:
        """
        In specs with such a notion, return the URIs in the dynamic scope.
        """
        for uri in self._previous:
            yield uri, self._registry

    def _evolve(self, base_uri: str, **kwargs: Any):
        """
        Evolve, appending to the dynamic scope.
        """
        previous = self._previous
        if self._base_uri and (not previous or base_uri != self._base_uri):
            previous = previous.cons(self._base_uri)
        return evolve(self, base_uri=base_uri, previous=previous, **kwargs)


@frozen
class Anchor(Generic[D]):
    """
    A simple anchor in a `Resource`.
    """

    name: str
    resource: Resource[D]

    def resolve(self, resolver: Resolver[D]):
        """
        Return the resource for this anchor.
        """
        return Resolved(contents=self.resource.contents, resolver=resolver)
