from __future__ import absolute_import, division, print_function

from collections import OrderedDict
import difflib
from itertools import count, takewhile
import pipes

from langkit import names
from langkit.c_api import CAPIType
from langkit.common import is_keyword
from langkit.compile_context import CompileCtx, get_context
from langkit.diagnostics import (
    Context, Severity, WarningSet, check_source_language,
    extract_library_location
)
from langkit.utils import (issubtype, memoized, not_implemented_error,
                           self_memoized)
from langkit.utils.text import (append_paragraph, first_line_indentation,
                                indent)
from langkit.utils.types import TypeSet


def gdb_helper(*args):
    """
    Format given arguments into a special Ada comment for GDB helpers.

    :param list[str] args: Elements of the special comment.
    :rtype: str
    """
    return '--# {}'.format(' '.join(pipes.quote(a) for a in args))


def precise_types_doc(label, types):
    """
    Helper to format documentation about precise types.

    :param str label: Label for the precise types.
    :param list[CompiledType] types: List of precise types to describe.
    :rtype: str
    """
    return '\n'.join([label, ''] + sorted('* {}'.format(t.dsl_name)
                                          for t in types))


@CompileCtx.register_template_extensions
def template_extensions(ctx):
    capi = ctx.c_api_settings
    root_entity = ctx.root_grammar_class.entity

    # Name of the root AST node access type
    type_name = ctx.root_grammar_class.name

    # Name of the root AST node record type
    value_type = type_name + names.Name('Type')

    # Name of the root AST node kind type
    kind_name = root_entity.api_name + names.Name('Kind_Type')

    # Likewise, for the generic list type
    glist_type_name = ctx.generic_list_type.name
    glist_value_type = ctx.generic_list_type.name + names.Name('Type')

    return {
        'no_builtins': lambda ts: filter(lambda t: not t.is_builtin(), ts),
        'grammar_rule_type':     T.GrammarRule.c_type(capi).name,
        'default_grammar_rule':  capi.get_name('default_grammar_rule'),
        'root_node_type_name':   type_name,
        'root_node_value_type':  value_type,
        'root_node_kind_name':   kind_name,
        'generic_list_type_name': glist_type_name,
        'generic_list_value_type': glist_value_type,
        'root_entity':           root_entity,
        'entity_array':          root_entity.array.api_name,
        'ctx':                   ctx,
        'ada_lib_name':          ctx.ada_api_settings.lib_name,
        'T':                     T,
        'ada_api':               ctx.ada_api_settings,
        'capi':                  capi,
        'bool_type':             T.Bool.c_type(capi).name,
        'analysis_context_type': CAPIType(capi, 'analysis_context').name,
        'analysis_unit_type':    T.AnalysisUnit.c_type(capi).name,
        'node_kind_type':        CAPIType(capi, 'node_kind_enum').name,
        'node_type':             ctx.root_grammar_class.c_type(capi).name,
        'entity_type':           T.entity.c_type(capi).name,
        'symbol_type':           T.Symbol.c_type(capi).name,
        'env_rebindings_type':   T.EnvRebindings.c_type(capi).name,
        'unit_kind_type':        T.AnalysisUnitKind.c_type(capi).name,
        'unit_provider_type':    CAPIType(capi, 'unit_provider').name,
        'unit_provider_destroy_type':
            CAPIType(capi, 'unit_provider_destroy_callback').name,
        'unit_provider_get_unit_filename_type':
            CAPIType(capi,
                     'unit_provider_get_unit_filename_callback').name,
        'unit_provider_get_unit_from_name_type':
            CAPIType(capi,
                     'unit_provider_get_unit_from_name_callback').name,
        'token_kind':            CAPIType(capi, 'token_kind').name,
        'token_type':            CAPIType(capi, 'token').name,
        'sloc_type':             CAPIType(capi, 'source_location').name,
        'sloc_range_type':
            T.SourceLocationRange.c_type(capi).name,
        'text_type':             CAPIType(capi, 'text').name,
        'big_integer_type':      CAPIType(capi, 'big_integer').name,
        'diagnostic_type':       CAPIType(capi, 'diagnostic').name,
        'exception_type':        CAPIType(capi, 'exception').name,
        'exception_kind_type':   CAPIType(capi, 'exception_kind').name
    }


class CompiledTypeRepo(object):
    """
    Namespace class: Repository for every compiled type. This is used to have a
    comprehensive list of every compiled type instance, so that you can use a
    TypeRepo instance to refer to any compiled type.
    """

    type_dict = {}
    """
    Mapping: type name -> CompiledType instance. Used in TypeRepo for type
    lookup by name.

    :rtype: dict[str, CompiledType]
    """

    enum_types = []
    """
    List of EnumType instances. This list is updated every time a new instance
    is created.

    :type: list[EnumType]
    """

    astnode_types = []
    """
    List of ASTNodeType instances. This list is updated every time a new
    instance is created.

    :type: list[ASTNodeType]
    """

    struct_types = []
    """
    List of all StructType instances.

    :type: list[StructType]
    """

    pending_list_types = []
    """
    Set of ASTNodeType instances for list types that are created while there
    is no context.

    :type: list[ASTNodeType]
    """

    array_types = set()
    """
    Set of all created ArrayType instances.

    :type: set[langkit.compiled_types.ArrayType]
    """

    root_grammar_class = None
    """
    The ASTNodeType instances used as a root type. Every other ASTNodeType
    instances must derive directly or indirectly from that class.

    :type: ASTNodeType
    """

    env_metadata = None
    """
    The StrucType instances used as metadata for the lexical environments
    values.

    :type: StructType
    """

    entity_info = None
    """
    The StructType instances to contain all entity information, except the node
    itself.

    :type: StructType
    """

    @classmethod
    def reset(cls):
        """
        Make this holder empty again. Useful to use Langkit multiple times in a
        process.
        """
        cls.type_dict = {}
        cls.enum_types = []
        cls.astnode_types = []
        cls.struct_types = []
        cls.pending_list_types = []
        cls.array_types = set()
        cls.root_grammar_class = None
        cls.env_metadata = None
        cls.entity_info = None


class AbstractNodeData(object):
    """
    This class defines an abstract base class for fields and properties on
    AST nodes.

    It defines the basis of what is needed to bind them in other languages
    bindings: a type and a name.
    """

    # Hack: the field declarations order in AST nodes matters.  The simple and
    # very handy syntax we use here for such declarations doesn't preserve this
    # order in Python2, however.  Waiting for the move to Python3, we use a
    # hack here: the following counter will help us to recover the declaration
    # order (assuming it is the same as the Field instantiation order).
    _counter = iter(count(0))

    is_property = False
    """
    Whether this class is Property (to be overriden in the Property subclass).
    :type: bool
    """

    is_user_field = False
    """
    Whether this class is UserField.
    :type: bool
    """

    PREFIX_FIELD = names.Name('F')
    PREFIX_PROPERTY = names.Name('P')
    PREFIX_INTERNAL = names.Name('Internal')

    # Name to use for the implicit entity information argument in field
    # accessors.
    entity_info_name = names.Name('E_Info')

    prefix = None
    """
    This can be overriden in subclasses of AbstractNodeData to add a prefix to
    the name of AbstractNodeData instances.

    :type: names.Name|None
    """

    _abstract = False

    def __init__(self, name=None, public=True, access_needs_incref=False,
                 internal_name=None):
        """
        :param names.Name|None name: Name for this field. Most of the time,
            this is initially unknown at field creation, so it is filled only
            at struct creation time.

        :param bool|None public: Whether this AbstractNodeData instance is
            supposed to be public or not.

            In the context of properties only, None is also allowed: in this
            case, inherit vibility from parents. If there is no property to
            override and None is passed, make the property private. This is
            computed in the "compute" pass.

        :param bool access_needs_incref: If True, field access evaluation does
            not create an ownership share: callers must call Inc_Ref
            themselves. See the eponym property.

        :param None|names.Name internal_name: If provided, override the default
            name to use in code generation for this node data.
        """
        self._serial = next(self._counter)
        self._is_public = public

        self.location = extract_library_location()

        self._name = name

        assert internal_name is None or isinstance(internal_name, names.Name)
        self._internal_name = internal_name

        self._original_name = None
        """
        Name for this property as specified in the DSL, if different from the
        current name.

        :type: names.Name
        """
        if name:
            self._original_name = name

        self.struct = None
        """
        StructType subclass that declared this field. Initialized when creating
        StructType subclasses.
        :type: StructType
        """

        self.arguments = []
        """
        Code generation-wise, all node data can be considered as functions
        which take at least a mandatory Self argument and return the
        corresponding data.

        This is a list that describes all other arguments. Note that only
        Property instances accept other arguments.

        :type: list[Argument]
        """

        self._uses_entity_info = False
        self._has_self_entity = False
        self.optional_entity_info = False
        self._access_needs_incref = access_needs_incref

    @property
    def abstract(self):
        """
        Return whether this field is abstract. This can be true only for
        properties and syntax fields.

        :rtype: bool
        """
        return self._abstract

    @property
    def base(self):
        """
        If this field overrides an inherited one in a base class, return the
        inherited one, otherwise return None.

        :rtype: AbstractNodeData|None
        """
        assert self._name and self.struct and self.struct.is_ast_node

        # Look for a potential field which has the same name as `self` in the
        # base struct.
        name_key = self._name.lower
        parent_cls = self.struct.base
        parent_fields = (parent_cls.get_abstract_node_data_dict()
                         if parent_cls else {})
        return parent_fields.get(name_key, None)

    @property
    def is_overriding(self):
        """
        Return whether this field overrides an inheritted one in a base class.

        :rtype: bool
        """
        return self.base is not None

    @property
    def uses_entity_info(self):
        """
        Return whether evaluating this field requires entity info.

        :rtype: bool
        """
        assert self._uses_entity_info is not None
        return self._uses_entity_info

    @property
    def diagnostic_context(self):
        ctx_message = 'in {}.{}'.format(self.struct.dsl_name, self._name.lower)
        return Context(ctx_message, self.location)

    @property
    def is_public(self):
        """
        Whether this field is private.
        :rtype: bool
        """
        assert self._is_public is not None
        return self._is_public

    @property
    def is_private(self):
        """
        Whether this field is public.

        This is a shortcut for::
            not self.is_public

        :rtype: bool
        """
        return not self.is_public

    @property
    def is_internal(self):
        """
        Whether this property is internal.
        :rtype: bool
        """
        return self.prefix == AbstractNodeData.PREFIX_INTERNAL

    @property
    def type(self):
        """
        Type of the abstract node field.
        :rtype: langkit.compiled_types.CompiledType
        """
        raise not_implemented_error(self, type(self).type)

    @type.setter
    def type(self, type):
        raise not_implemented_error(self, type(self).type)

    @property
    def public_type(self):
        return self.type.public_type

    def c_type_or_error(self, capi):
        """
        Within a diagnostic context for this field, return its C API type.

        :rtype: CAPIType
        """
        with self.diagnostic_context:
            return self.public_type.c_type(capi)

    def _prefixed_name(self, name):
        """
        Decorate `name` with this AbstractNodeData's prefix.

        :rtype: names.Name
        """
        assert name

        # If this is an internal property, the name has an underscore
        # prefix that we want to get rid of for code generation.
        radix = (names.Name(name.base_name[1:])
                 if self.is_internal else
                 name)

        return self.prefix + radix if self.prefix else radix

    @property
    @self_memoized
    def name(self):
        """
        :rtype: names.Name
        """
        return self._prefixed_name(self._name)

    @name.setter
    def name(self, name):
        assert isinstance(name, names.Name)
        self._name = name
        if self._original_name is None:
            self._original_name = name

    @property
    def internal_name(self):
        """
        Name of the field in the generated code.

        :rtype: names.Name
        """
        if self._internal_name:
            return self._internal_name
        else:
            return self.name

    @property
    def original_name(self):
        """
        :rtype: names.Name
        """
        assert self._original_name
        return self._original_name

    @property
    def qualname(self):
        """
        Return the qualified name for this field, i.e. the name of the owning
        type plus the name of the field itself. This is useful for diagnostic
        messages.

        Note that if expansion renamed this property, this will return the
        original (DSL-level) name.

        :rtype: str
        """
        return '{}.{}'.format(
            self.struct.dsl_name if self.struct else '<unresolved>',
            (self.original_name.lower
             if self._original_name else '<unresolved>')
        )

    def __repr__(self):
        return '<{} {}>'.format(
            type(self).__name__,
            self.qualname
        )

    @property
    def doc(self):
        """
        Documentation for the abstract node field.
        :rtype: str
        """
        raise not_implemented_error(self, type(self).doc)

    @property
    def accessor_basename(self):
        """
        Return the base name for the accessor we generate for this field.

        Note that this is available only for fields attached to AST nodes.

        :rtype: names.Name
        """
        assert self.struct
        return self.struct.kwless_raw_name + self.name

    @property
    def natural_arguments(self):
        """
        Return the subset of "self.arguments" that are non-artificial
        arguments, that is to say the subset that users actually handle in
        expressions.

        This property makes sense in user-facing layers.

        :rtype: list[Argument]
        """
        return self.arguments

    @property
    def access_needs_incref(self):
        """
        Return whether field access evaluation does not create an ownership
        share. In this case, users must call Inc_Ref themselves. This returns
        always False for node data whose type is not ref-counted.

        :rtype: bool
        """
        return self.type.is_refcounted and self._access_needs_incref

    @property
    def introspection_enum_literal(self):
        """
        Return the name of the enumeration literal to use to represent this
        field. Note that this is valid only on syntax fields or properties, and
        these must not be overriding.

        :rtype: str
        """
        from langkit.expressions import PropertyDef

        assert isinstance(self, (Field, PropertyDef))
        assert self.abstract or not self.overriding, (
            'Trying to get introspection enumeration literal for overriding'
            ' field {}'.format(self.qualname))
        return (self.struct.entity.api_name + self.name).camel_with_underscores


class CompiledType(object):
    """
    Descriptor for a type in the generated code.
    """

    def __init__(self, name, location=None, doc='', is_ptr=True,
                 has_special_storage=False, is_list_type=False,
                 is_entity_type=False, should_emit_array_type=True,
                 exposed=False, c_type_name=None, external=False,
                 null_allowed=False, is_ada_record=False, is_refcounted=False,
                 nullexpr=None, py_nullexpr=None, element_type=None,
                 hashable=False, has_equivalent_function=False,
                 type_repo_name=None, api_name=None, dsl_name=None,
                 introspection_prefix=None, conversion_requires_context=False):
        """
        :param names.Name|str name: Type name. If a string, it must be
            camel-case.

        :param langkit.diagnostics.Location|None location: Location of the
            declaration of this compiled type, or None if this type does not
            come from a language specficication.

        :param str doc: User documentation for this type.

        :param bool is_ptr: Whether this type is handled through pointers only
            in the generated code.

        :param bool has_special_storage: Whether this type uses a special type
            for storage in structs and AST nodes.  If this is true, the
            following methods may be overriden:

              * storage_type_name;
              * storage_nullexpr;
              * extract_from_storage_expr;
              * convert_to_storage_expr.

        :param bool is_list_type: Whether this type is an AST node that is a
            list of AST nodes.

        :param bool is_entity_type: Whether this type represents an entity
            type.

        :param bool should_emit_array_type: Whether declarations for this
            compiled typed's array type are generated along with all regular
            array types. It must be False for several special types (for
            instance, the root AST node), for which the array type declarations
            are hard-wired in the $.Analysis package.

        :param bool exposed: Whether the type should be exposed to the C and
            Python APIs. Note that all types are exposed anyway when the
            current context has the "library_all_fields_public" attribute set
            to True.

        :param str|None c_type_name: Name for the type as it will appear in the
            C API. If left to None, `name` will be used instead.

        :param bool external: See CAPIType.__init__: this will be forwarded to
            it.

        :param bool null_allowed: Whether a client is allowed to create a null
            value for this type. Note that a type might have a nullexpr and
            still have null disallowed, because nullexpr might make sense for
            initialization purposes in the parsers, but not as a real null
            value.

        :param bool is_ada_record: Whether the type used in the C API is
            implemented as an Ada record. If so, we must pass them by reference
            in for C API interface functions.

        :param bool is_refcounted: Return whether this type matters for the
            ref-counting mechanism. See the "is_refcounted" method.

        :param str|None nullexpr: Null expression to use in Ada for this type.
            See the "nullexpr" method.

        :param str|None py_nullexpr: Null expression to use in Python for this
            type. See the "py_nullexpr" method.

        :param CompiledType|None element_type: If this is a collection type,
            must be the corresponding element type. Must be None otherwise.

        :param bool hashable: Whether this type has a Hash primitive, so that
            it can be used as a key in hashed maps/sets.

        :param bool has_equivalent_function: Whether testing equivalence for
            two values of this type must go through an Equivalent function. If
            not, code generation will use its "=" operator.

        :param str|None type_repo_name: Name to use for registration in
            TypeRepo. The camel-case of "name" is used if left to None.

        :param names.Name|str|None api_name: If not None, must be the name of
            the type to use in the public Ada API. Strings are interpreted as
            camel case.

        :param str|None dsl_name: If provided, name used to represent this type
            at the DSL level. Useful to format diagnostics.

        :param str|None introspection_prefix: If provided, override the default
            value to return in the introspection_prefix property.

        :param bool conversion_requires_context: Whether converting this type
            from public to internal values requires an analysis context.
    """
        if isinstance(name, str):
            name = names.Name.from_camel(name)
        if isinstance(api_name, str):
            api_name = names.Name.from_camel(api_name)

        self._name = name
        self.location = location
        self._doc = doc
        self.is_ptr = is_ptr
        self.has_special_storage = has_special_storage
        self.is_list_type = is_list_type
        self.is_entity_type = is_entity_type
        self.should_emit_array_type = should_emit_array_type
        self.c_type_name = c_type_name
        self.external = external
        self.exposed = exposed
        self.null_allowed = null_allowed
        self.is_ada_record = is_ada_record
        self._is_refcounted = is_refcounted
        self._nullexpr = nullexpr
        self._py_nullexpr = py_nullexpr
        self._element_type = element_type
        self.hashable = hashable
        self._has_equivalent_function = has_equivalent_function
        self._requires_hash_function = False
        self._api_name = api_name
        self._dsl_name = dsl_name
        self._introspection_prefix = introspection_prefix

        type_repo_name = type_repo_name or dsl_name or name.camel
        CompiledTypeRepo.type_dict[type_repo_name] = self

        self._conversion_requires_context = conversion_requires_context

        # If this type does not have public/internal converters, these are not
        # used. Otherwise, they indicate whether these should be generated.
        self.to_public_converter_required = False
        self.to_internal_converter_required = False

        self.used_in_public_struct = False
        """
        Whether this type is used as a field in a struct that belongs to the
        public API.
        """

        self._abstract_node_data_dict_cache = {}
        """
        Cache for the get_abstract_node_data_dict class method.

        :type: dict[(bool, AbstractNodeData), dict[str, BaseField]]
        """

        self._fields = OrderedDict()
        """
        List of AbstractNodeData fields for this type.
        """

    def __lt__(self, other):
        assert isinstance(other, CompiledType)
        return self.name < other.name

    @property
    def public_type(self):
        """
        Return the type to use when exposing values in public APIs.

        This returns `self` for most types, but some (such as bare nodes) are
        automatically wrapped as entity.

        :rtype: langkit.compiled_types.CompiledType
        """
        return self

    @property
    def conversion_requires_context(self):
        return self._conversion_requires_context

    @property
    def has_equivalent_function(self):
        return self._has_equivalent_function

    @property
    def requires_hash_function(self):
        """
        Return whether code generation must produce a Hash function for this
        type.

        :rtype: bool
        """
        return self._requires_hash_function

    def require_hash_function(self):
        """
        Tag this type as requiring a hash function.
        """
        self._requires_hash_function = True

    def add_as_memoization_key(self, context):
        """
        Add `self` to the set of types that are used as keys in the hashed maps
        used to implement properties memoization. It has to be hashable.
        """
        assert self.hashable, 'Trying to use {} as hashable type'.format(
            self.dsl_name
        )
        context.memoization_keys.add(self)
        self.require_hash_function()

    def add_as_memoization_value(self, context):
        """
        Add `self` to the set of types that are used as values in the hashed
        maps used to implement properties memoization.
        """
        context.memoization_values.add(self)

    @property
    def memoization_kind(self):
        """
        Return the enumerator name that corresponds to this type for the
        discriminated record to materialize memoization keys/values.

        :rtype: str
        """
        return (names.Name('Mmz') + self.name).camel_with_underscores

    @property
    def introspection_prefix(self):
        """
        Return the root name used to describe this type in the introspection
        API.

        :rtype: str
        """
        return self._introspection_prefix or self.api_name

    @property
    def introspection_kind(self):
        """
        Return the enumerator name that corresponds to this type for the
        discriminated record to materialize values in the introspection API.

        :rtype: str
        """
        return '{}_Value'.format(self.introspection_prefix)

    @property
    def introspection_constraint(self):
        """
        Return an Ada expression that computes the value constraint
        corresponding to this type in the introspection API.

        :rtype: str
        """
        result = '(Kind => {}'.format(self.introspection_kind)
        if self.is_ast_node or self.is_entity_type:
            node = self if self.is_ast_node else self.element_type
            result += ', Node_Type => {}'.format(node.introspection_name)
        return result + ')'

    @property
    def name(self):
        """
        Name of the type for general values in the Ada generated code.

        :rtype: names.Name
        """
        return self._name

    @property
    def api_name(self):
        """
        Name of public type. By default, it is the same as `name`.

        :rtype: names.Name
        """
        return self.name if self._api_name is None else self._api_name

    @property
    def dsl_name(self):
        """
        Type name as it appears in the DSL. To be used in diagnostics.

        :rtype: str
        """
        return self._dsl_name or self.name.camel

    @property
    def to_public_converter(self):
        """
        If this type requires a conversion in public properties, return the
        name of the function that takes an internal value and returns a public
        one. Return None otherwise.

        :rtype: names.Name|None
        """
        return None

    @property
    def to_internal_converter(self):
        """
        If this type requires a conversion in public properties, return the
        name of the function that takes a public value and returns an internal
        one. Return None otherwise.

        :rtype: names.Name|None
        """
        return None

    def to_public_expr(self, internal_expr):
        """
        Given ``internal_expr``, an expression that computes an internal value,
        for this type return another expression that converts it to a public
        value.

        :type internal_expr: str
        :rtype: str
        """
        if self.to_public_converter:
            return '{} ({})'.format(self.to_public_converter, internal_expr)
        else:
            # By default, assume public and internal types are identical, i.e.
            # that we can return the internal value as-is.
            assert self.name == self.api_name, (
                'Trying to avoid conversion while internal type is {} and'
                ' public type is {}'.format(self.name, self.api_name)
            )
            return internal_expr

    def to_internal_expr(self, public_expr, context=None):
        """
        Given ``public_expr``, an expression that computes a public value, for
        this type return another expression that converts it to an internal
        value.

        :type public_expr: str
        :param str|None context: If this type requires the context for this
            conversion, this must be an expression that yields the context.
        :rtype: str
        """
        requires_context = self.conversion_requires_context
        assert not (requires_context and context is None)

        if self.to_internal_converter:
            return '{} ({}{})'.format(
                self.to_internal_converter,
                public_expr,
                (', ' + context) if requires_context else ''
            )
        else:
            # By default, assume public and internal types are identical, i.e.
            # that we can return the internal value as-is.
            assert self.name == self.api_name
            return public_expr

    def __repr__(self):
        return '<CompiledType {}>'.format(self.name.camel)

    @property
    def diagnostic_context(self):
        ctx_message = 'in {}'.format(self.dsl_name)
        return Context(ctx_message, self.location)

    @property
    def doc(self):
        """
        Return the user documentation for this type, or None if there is no
        documentation.

        :rtype: None|str
        """
        return self._doc

    @property
    def is_analysis_unit_type(self):
        """
        Return whether this is the analysis unit type.
        """
        return self == T.AnalysisUnit

    @property
    def is_analysis_unit_kind(self):
        """
        Return whether this is the analysis unit kind type.
        """
        return self == T.AnalysisUnitKind

    @property
    def is_array_type(self):
        """
        Return whether this is an instance of ArrayType.
        """
        return isinstance(self, ArrayType)

    @property
    def is_bool_type(self):
        """
        Return whether this is the boolean type.

        :rtype: bool
        """
        return self == T.Bool

    @property
    def is_int_type(self):
        """
        Return whether this is the integer type.

        :rtype: bool
        """
        return self == T.Int

    @property
    def is_big_int_type(self):
        """
        Return whether this is the big integer type.

        :rtype: bool
        """
        return self == T.BigInt

    @property
    def is_enum_type(self):
        """
        Return whether this is an enumeration type.

        :rtype: bool
        """
        return isinstance(self, EnumType)

    @property
    def is_collection(self):
        """
        Return whether this is a collection type.

        :rtype: bool
        """
        return self._element_type is not None

    @property
    def is_env_rebindings_type(self):
        """
        Return whether this is the env rebindings type.

        :rtype: bool
        """
        return self == T.EnvRebindings

    @property
    def is_equation_type(self):
        """
        Return whether this is the equation type.

        :rtype: bool
        """
        return self == T.Equation

    @property
    def is_lexical_env_type(self):
        """
        Return whether this is the lexical environment type.

        :rtype: bool
        """
        return self == T.LexicalEnv

    @property
    def is_logic_var_type(self):
        """
        Return whether this is an instance of LogicVarType.

        :rtype: bool
        """
        return isinstance(self, LogicVarType)

    @property
    def is_long_type(self):
        """
        Return whether this is a integer type.

        :rtype: bool
        """
        return self == T.Int

    @property
    def is_character_type(self):
        """
        Return whether this is a character type.

        :rtype: bool
        """
        return self == T.Character

    @property
    def is_string_type(self):
        """
        Return whether this is an array of character type.

        :rtype: bool
        """
        return self.is_array_type and self.element_type.is_character_type

    @property
    def is_symbol_type(self):
        """
        Return whether this is a symbol type.

        :rtype: bool
        """
        return self == T.Symbol

    @property
    def is_token_type(self):
        """
        Return whether this is a token type.

        :rtype: bool
        """
        return self == T.Token

    @property
    def is_big_integer_type(self):
        """
        Return whether this is a big integer type.

        :rtype: bool
        """
        return self == T.BigInt

    @property
    def element_type(self):
        """
        Assuming this is a collection type (array or list) or an entity, return
        the corresponding element type.

        :rtype: CompiledType
        """
        assert self._element_type
        return self._element_type

    @property
    def is_refcounted(self):
        """
        Return whether this type matters for the ref-counting mechanism.

        This returns whether this type is dynamically allocated and thus
        ref-counted, or whether it owns ref-counted values. "dynamically" in
        this context means: with a lifetime that is different from the owning
        analysis unit.

        If it is ref-counted, there must exist Inc_Ref and Dec_Ref primitives.
        The Dec_Ref primitive must handle null values correctly (i.e. ignore
        them).

        :rtype: bool
        """
        return self._is_refcounted

    @property
    def storage_type_name(self):
        """
        Return the name of the type that is used to store instances of this
        type in structs and AST nodes. See documentation for
        has_special_storage.

        :rtype: str
        """
        return self.name

    def extract_from_storage_expr(self, node_expr, base_expr):
        """
        Turn a storage value into a public value. See documentation for
        has_special_storage.

        :param str node_expr: Expression that yields the node that owns the
            storage value.
        :param str base_expr: Expression that yields the storage value.
        :return: An expression that yields the public value.
        :rtype: str
        """
        return base_expr

    def convert_to_storage_expr(self, node_expr, base_expr):
        """
        Turn a public value into a storage value. See documentation for
        has_special_storage.

        :param str node_expr: Expression that yields the node that will own the
            resulting storage value.
        :param str base_expr: Expression that yields the public value:
        :return: An expression that yields the storage value.
        :rtype: str
        """
        return base_expr

    @property
    def nullexpr(self):
        """
        Return a string to be used in code generation for "null" expressions.

        Must be overriden in subclasses.

        :rtype: str
        """
        if self._nullexpr is None:
            raise not_implemented_error(self, type(self).nullexpr)
        else:
            return self._nullexpr

    @property
    def py_nullexpr(self):
        """
        Return a string to be used in Python code gen for "null" expressions.

        Must be overridden in subclasses... for which we need the Python null
        expression.

        :rtype: str
        """
        if self._py_nullexpr is None:
            raise not_implemented_error(self, type(self).py_nullexpr)
        else:
            return self._py_nullexpr

    @property
    def storage_nullexpr(self):
        """
        Return the nullexpr that is used for fields of this type in structs and
        ASTNodes. See documentation for has_special_storage.

        :rtype: str
        """
        return self.nullexpr

    def c_type(self, c_api_settings):
        """
        Return a CAPIType instance for this type.

        :param CAPISettings c_api_settings: The settings for the C API.
        """
        return CAPIType(c_api_settings, self.c_type_name or self.name,
                        external=self.external)

    def unify(self, other, error_msg=None):
        """
        If `self` and `other` are types that match, return the most general
        type to cover both. Create an error diagnostic if they don't match.

        :param CompiledType other: Type to unify with `self`.
        :param str|None error_msg: Diagnostic message for mismatching types. If
            None, a generic one is used, otherwise, we call .format on it with
            the `self` and `other` keys being the names of mismatching types.
        :rtype: CompiledType
        """

        # ASTNodeType instances (and thus entities) always can be unified:
        # just take the most recent common ancestor.
        if self.is_entity_type and other.is_entity_type:
            return ASTNodeType.common_ancestor(self.element_type,
                                               other.element_type).entity
        elif self.is_ast_node and other.is_ast_node:
            return ASTNodeType.common_ancestor(self, other)

        # Otherwise, we require a strict subtyping relation
        check_source_language(
            self.matches(other),
            (error_msg or 'Mismatching types: {self} and {other}').format(
                self=self.dsl_name, other=other.dsl_name
            )
        )
        return self

    def matches(self, formal):
        """
        Return whether `self` matches `formal`.

        This is mere equality for all types but AST nodes, in which `self` is
        allowed to be a subtype for `formal`.

        :param CompiledType formal: Type to match. `self` is checked to be a
            subtype of it.
        :rtype: bool
        """

        if self.is_entity_type and formal.is_entity_type:
            return self.element_type.matches(formal.element_type)

        if formal.is_ast_node and self.is_ast_node:
            return formal in self.get_inheritance_chain()
        else:
            return self is formal

    # Memoize so that we have only one array type for each element type
    @property
    @memoized
    def array(self):
        """
        Create an array type whose element type is `self`.

        :rtype: ArrayType
        """
        return ArrayType(name=self.name + names.Name('Array_Type'),
                         element_type=self)

    @property
    def is_base_struct_type(self):
        return isinstance(self, BaseStructType)

    @property
    def is_struct_type(self):
        return isinstance(self, StructType)

    @property
    def is_ast_node(self):
        return isinstance(self, ASTNodeType)

    @property
    def is_array(self):
        return isinstance(self, ArrayType)

    @property
    def public_requires_boxing(self):
        """
        Whether the public type in the Ada API for this requires some boxing to
        be embedded in a record. This is true for all unbounded types (i.e.
        arrays).

        :rtype: bool
        """
        return False

    @property
    def exposed_types(self):
        """
        Return the list of types that ``self`` exposes when it is itself
        exposed.

        :rtype: list[CompiledType]
        """
        return []

    def new(self, *args, **kwargs):
        """
        Shortcut to the New expression, allowing type.new(..) syntax.

        :rtype: AbstractExpression
        """
        from langkit.expressions.structs import New
        return New(self, *args, **kwargs)

    def _init_fields(self, fields):
        """
        Bind input fields to `self` and initialize their name.

        :param list[(str|names.Name, AbstractNodeData)] fields: List of (name,
            field) for this struct's fields. Inheritted fields must not appear
            in this list.
        """
        for f_n, f_v in fields:
            f_v.name = (f_n if isinstance(f_n, names.Name) else
                        names.Name.from_lower(f_n))
            f_v.struct = self

            # Use the "hidden" name so that lookups work on undecorated field
            # names.
            self._fields[f_v._name.lower] = f_v

    def add_field(self, field):
        """
        Append a field to this Struct/AST node.

        :param AbstractNodeData field: Field to append.
        """
        self._fields[field._name.lower] = field
        field.struct = self

        # Invalidate the field lookup cache
        self._abstract_node_data_dict_cache = {}

    def get_user_fields(self, predicate=None, include_inherited=True):
        """
        Return the list of all the user fields `self` has, including its
        parents'.

        :param predicate: Predicate to filter fields if needed.
        :type predicate: None|(Field) -> bool

        :param bool include_inherited: If true, include inheritted fields in
            the returned list. Return only fields that were part of the
            declaration of this node otherwise.

        :rtype: list[UserField]
        """
        return self.get_abstract_node_data(predicate, include_inherited,
                                           field_class=UserField)

    def get_fields(self, predicate=None, include_inherited=True):
        """
        Return the list of all the fields `self` has, including its parents'.

        :param predicate: Predicate to filter fields if needed.
        :type predicate: None|(Field) -> bool

        :param bool include_inherited: If true, include inheritted fields in
            the returned list. Return only fields that were part of the
            declaration of this node otherwise.

        :rtype: list[BaseField]
        """
        return self.get_abstract_node_data(predicate, include_inherited,
                                           field_class=BaseField)

    def get_abstract_node_data(self, predicate=None, include_inherited=True,
                               field_class=AbstractNodeData):
        """
        Get all BaseField instances for the class.

        :param predicate: Predicate to filter fields if needed.
        :type predicate: None|(AbstractNodeData) -> bool

        :param bool include_inherited: If true, include inheritted fields in
            the returned list. Return only fields that were part of the
            declaration of this node otherwise.

        :param type field_class: The field class to use to filter fields.

        :rtype: list[AbstractNodeData]
        """
        result = filter(
            predicate or (lambda f: True),
            self.get_abstract_node_data_dict(include_inherited,
                                             field_class).values()
        )
        result.sort(key=lambda f: f._serial)
        return result

    def get_properties(self, predicate=None, include_inherited=True):
        """
        Return the list of all the fields `self` has.

        :param predicate: Predicate to filter fields if needed.
        :type predicate: None|(Field) -> bool

        :param bool include_inherited: If true, include inheritted fields in
            the returned list. Return only fields that were part of the
            declaration of this node otherwise.

        :rtype: list[langkit.expressions.base.PropertyDef]
        """
        return self.get_abstract_node_data(
            lambda f: f.is_property and (predicate is None or predicate(f)),
            include_inherited
        )

    def get_abstract_node_data_dict(self, include_inherited=True,
                                    field_class=AbstractNodeData):
        """
        Get all BaseField instances for the class.

        :param bool include_inherited: If true, include inheritted fields in
            the returned list. Return only fields that were part of the
            declaration of this node otherwise.

        :param type field_class: The field class to use to filter fields.

        :rtype: dict[str, AbstractNodeData]
        """
        assert issubclass(field_class, AbstractNodeData)

        # First, see if we have a cached result for this
        key = (include_inherited, field_class)
        try:
            return self._abstract_node_data_dict_cache[key]
        except KeyError:
            pass

        # No cached result, we have to compute it
        if field_class == AbstractNodeData:
            # If we don't filter by class (i.e. if we want the most general
            # class field: AbstractNodeData), do the base class recursion.
            if include_inherited and self.is_ast_node:
                result = OrderedDict()
                for base_class in self.get_inheritance_chain():
                    result.update(base_class._fields)
            else:
                result = OrderedDict(self._fields)

        # Otherwise, just rely on the potentially already cached whole list of
        # fields and do filtering.
        else:
            all_fields = self.get_abstract_node_data_dict(include_inherited)
            result = OrderedDict(
                filter(lambda kv: isinstance(kv[1], field_class),
                       all_fields.items())
            )

        self._abstract_node_data_dict_cache[key] = result
        return result


class NoCompiledType(CompiledType):
    """
    Special CompiledType singleton. Used to mean the absence of type. This is
    useful in special resolved expressions.
    """

    def is_refcounted(self):
        raise NotImplementedError()

no_compiled_type = NoCompiledType('NoCompiledType')


class LogicVarType(CompiledType):
    """
    Singleton for the logic variable type.

    This type represents a logical variable. A logical variable is a reference,
    that can take a specific value when it is bound to a specific Equation, and
    that equation is solved for a certain problem set.

    It is a special type in Langkit at this point, in that its value is
    initially undefined, and is mutated after the solve of an equation to a
    specific value. It is thus the only type in Langkit for the moment for
    which variables of the type can be mutated after creation.

    TODO: For the moment a logic variable is necessarily a holder around an
    ASTNodeType. At some point we might want to make it generic, like list and
    array types.
    """

    def __init__(self):
        super(LogicVarType, self).__init__(
            name='LogicVar',
            nullexpr='null',
            is_ptr=False,
            has_special_storage=True,
            c_type_name='logic_var_type',
        )

    @property
    def storage_type_name(self):
        return names.Name('Logic_Var_Record')

    @property
    def storage_nullexpr(self):
        return 'Null_Var_Record'

    def extract_from_storage_expr(self, node_expr, base_expr):
        del node_expr
        return "{}'Unrestricted_Access".format(base_expr)

    def convert_to_storage_expr(self, node_expr, base_expr):
        raise not_implemented_error(self, type(self.convert_to_storage_expr))


class EnvRebindingsType(CompiledType):
    """
    Singleton for the environment rebinding type.
    """

    def __init__(self):
        super(EnvRebindingsType, self).__init__(
            name='EnvRebindings',
            exposed=True,
            null_allowed=True,
            nullexpr='null',
            c_type_name='env_rebindings_type',
            is_refcounted=False,
            py_nullexpr='None',
            hashable=True,
        )


class TokenType(CompiledType):
    """
    Singleton for the token data type.
    """

    def __init__(self):
        super(TokenType, self).__init__(
            name='TokenReference',
            dsl_name='Token',
            introspection_prefix='Token',
            exposed=True,
            is_ptr=False,
            nullexpr='No_Token',
            is_ada_record=True,
            has_special_storage=True,
            c_type_name='token'
        )

    @property
    def storage_type_name(self):
        return 'Token_Index'

    @property
    def storage_nullexpr(self):
        return 'No_Token_Index'

    def extract_from_storage_expr(self, node_expr, base_expr):
        return 'Token ({}, {})'.format(node_expr, base_expr)

    def convert_to_storage_expr(self, node_expr, base_expr):
        return 'Stored_Token ({}, {})'.format(node_expr, base_expr)


class Argument(object):
    """
    Holder for properties arguments.
    """

    def __init__(self, name, type, is_artificial=False, default_value=None,
                 abstract_var=None):
        """
        :param names.Name name: Argument name.
        :param CompiledType type: Argument type.
        :param bool is_artificial: Whether the argument was automatically
            created by Langkit, i.e. the language specification did not mention
            it.
        :param ResolvedExpression|None default_value: If None, there is no
            default value associated to this argument. Otherwise, it must be a
            compile-time known resolved expression to be used when generating
            code for the corresponding property argument.
        :param AbstractVariable|None abstract_var: For properties only. If
            provided, use it as the abstract variable to reference this
            argument. If not provided, an AbstractVariable instance is
            automatically created.
        """
        from langkit.expressions.base import AbstractVariable
        self.name = name
        self.var = (abstract_var
                    or AbstractVariable(name, type, source_name=name))
        self.is_artificial = is_artificial
        self.default_value = default_value

    @property
    def type(self):
        return self.var.type

    @property
    def public_type(self):
        return self.type.public_type

    @property
    def public_default_value(self):
        """
        Assuming this argument has a default value, return the default value to
        use in public APIs, according to the type exposed in public.

        :rtype: ResolvedExpression
        """
        from langkit.expressions import NullExpr

        assert self.default_value is not None

        if not self.type.is_ast_node:
            return self.default_value

        if isinstance(self.default_value, NullExpr):
            return NullExpr(self.public_type)
        else:
            assert False, 'Unsupported default value'

    @property
    def dsl_name(self):
        return self.name.lower

    def __repr__(self):
        return '<Argument {} : {}>'.format(self.dsl_name, self.type.dsl_name)


class BaseField(AbstractNodeData):
    """
    Base class for node fields and structure fields.
    """

    concrete = False
    """
    Field used to prevent instantiation of the class. Concrete descendants
    of BaseField must put that field to True in their definition.
    """

    prefix = AbstractNodeData.PREFIX_FIELD

    _null = False

    def __init__(self, repr=True, doc='', type=None,
                 access_needs_incref=False, internal_name=None):
        """
        Create an AST node field.

        :param bool repr: If true, the field will be displayed when
            pretty-printing the embedding AST node.
        :param str doc: User documentation for this field.
        :param bool access_needs_incref: See AbstractNodeData's constructor.
        :param None|names.Name internal_name: See AbstractNodeData's
            constructor.
        """

        assert self.concrete, 'BaseField itself cannot be instantiated'

        super(BaseField, self).__init__(
            public=True, access_needs_incref=access_needs_incref,
            internal_name=internal_name
        )

        self.repr = repr
        self._name = None
        self._doc = doc

        self.should_emit = True
        """
        Subclasses can change that variable to trigger wether the field
        should be emitted or not.
        """

        self._type = type
        """
        Type of the field. If not set, it will be set to a concrete
        CompiledType subclass after type resolution. If set, it will be
        verified at type resolution time.
        :type: CompiledType
        """

    @property
    def type(self):
        """
        :rtype: CompiledType
        """
        self._type = resolve_type(self._type)
        return self._type

    @type.setter
    def type(self, typ):
        assert isinstance(typ, CompiledType)
        self._type = typ

    def __repr__(self):
        return '<ASTNode {} Field({})>'.format(self._serial, self.qualname)

    @property
    def doc(self):
        return self._doc

    @property
    def null(self):
        """
        Return whether this field is always supposed to be null.

        :rtype: bool
        """
        return self._null


class Field(BaseField):
    """
    Fields that are meant to store parsing results. Can be used only on
    subclasses of ASTNodeType.
    """
    concrete = True

    def __init__(self, repr=True, doc='', type=None, abstract=False,
                 null=False):
        super(Field, self).__init__(repr, doc, type)

        assert not abstract or not null
        self._abstract = abstract
        self._null = null

        self._overriding_computed = False
        self._overriding = None
        self._concrete_fields = []

        self.parsers_from_transform = []
        """
        List of parsers that provide a value for this field. Such parsers are
        children of Transform parsers.

        :type: list[langkit.parsers.Parser]
        """

        self._precise_types = None
        """
        Cache for the precise_types property.

        :type: TypeSet
        """

        self._precise_element_types = None
        """
        Cache for the precise_element_types property.

        :type: TypeSet
        """

        self._is_optional = None
        """
        Whether this field is ever produced by a parser in the user grammar
        which is allowed to return null nodes, meaning this field is optional.

        :type: bool
        """

        self._index = None
        """
        0-based index for this parsing field in the owning AST node's children
        list. This is -1 for abstract or null fields.

        :type: int
        """

    @property
    def precise_types(self):
        """
        Return the precise set of types that this field can contain.

        This is the same as ``TypeSet([self.type])`` except for nodes created
        during parsing: for these, ``self.type`` might be too general.

        :rtype: TypeSet
        """
        assert self._precise_types is not None
        return self._precise_types

    @property
    def precise_element_types(self):
        """
        For fields that contain lists, return the precise set of types that
        these list can contain.

        :rtype: TypeSet
        """
        assert self.type.is_list_type
        assert self._precise_element_types is not None
        return self._precise_element_types

    @property
    def is_optional(self):
        """
        Return whether this field is ever produced by a parser in the user
        grammar which is allowed to return null nodes, meaning this field is
        optional.

        :rtype: bool
        """
        assert self._is_optional is not None
        return self._is_optional

    def _compute_precise_types(self):
        etypes = None
        is_list = self.type.is_list_type

        if self.null:
            # Null fields have their type automatically computed from the
            # abstract field they override.
            types = TypeSet([self.type])
            if is_list:
                etypes = TypeSet([self.type.element_type])

        elif self.abstract:
            # Abstract fields can contain anything the corresponding concrete
            # one accept, thanks to the laws of inheritance.
            types = TypeSet()
            if is_list:
                etypes = TypeSet()
            for f in self.concrete_fields:
                f._compute_precise_types()
                types.update(f.precise_types)
                if is_list:
                    etypes.update(f.precise_element_types)

        elif self.struct.synthetic:
            types = TypeSet([self.type])
            if is_list:
                etypes = TypeSet([self.type.element_type])

        else:
            # For regular
            types = TypeSet()
            if is_list:
                etypes = TypeSet()
            for p in self.parsers_from_transform:
                types.update(p.precise_types)
                if is_list:
                    etypes.update(p.precise_element_types)

        self._precise_types = types
        self._precise_element_types = etypes

    @property
    def doc(self):
        # If parsers build this field, add a precise list of types it can
        # contain: the field type might be too generic.

        result = super(Field, self).doc

        # Synthetic nodes are not built by parsers, so for now we don't have
        # precise type information for them.
        if self.struct.synthetic:
            return result

        def amended(label, types):
            return append_paragraph(result, precise_types_doc(label, types))

        precise_types = self.precise_types.minimal_matched_types

        # If the field always contains a list, try to give precise types
        # for the list items.
        if len(precise_types) == 1 and self.type.is_list_type:
            precise_element_types = (self.precise_element_types
                                     .minimal_matched_types)
            if len(precise_element_types) > 1:
                return amended(
                    'This field contains a list that itself contains'
                    ' one of the following nodes:',
                    precise_element_types)

        if len(precise_types) > 1:
            return amended(
                'This field can contain one of the following nodes:',
                precise_types)

        return result

    @property
    def overriding(self):
        """
        If this field overrides an abstract field, return the abstract field.
        return None otherwise.

        :rtype: None|Field
        """
        assert self._overriding_computed, (
            '"overriding" not computed for {}'.format(self.qualname))
        return self._overriding

    @overriding.setter
    def overriding(self, overriding):
        assert not self._overriding_computed
        self._overriding_computed = True
        self._overriding = overriding
        if overriding:
            overriding._concrete_fields.append(self)

    @property
    def concrete_fields(self):
        """
        Assuming this field is abstract, return the list of concrete fields
        that override it.

        :rtype: list[Field]
        """
        assert self.abstract and self._overriding_computed
        return self._concrete_fields

    @property
    def index(self):
        """
        Return the 0-based index of this parsing field in the owning AST node's
        children list. Only non-null concrete fields have an index.

        :rtype: int
        """
        assert self._index is not None, (
            'Index for {} is not computed'.format(self.qualname))
        assert self._index != -1, (
            'Trying to get index of abstract/null field {}'
            .format(self.qualname))
        return self._index


class UserField(BaseField):
    """
    Fields that are not meant to store parsing results. Can be used on any
    Node type, will be ignored by the parsing code.
    """

    prefix = None
    is_user_field = True

    def __init__(self, type, repr=False, doc='', public=True,
                 access_needs_incref=True, internal_name=None):
        """
        See inherited doc. In this version we just ensure that a type is
        passed because it is mandatory for data fields. We also set repr to
        False because most of the time you don't want User fields to show up in
        the pretty printer.

        :type type: CompiledType
        :type doc: str

        :param bool is_public: Whether this field is public in the generated
            APIs.

        :param bool access_needs_incref: See AbstractNodeData's constructor.

        :param None|names.Name internal_name: See AbstractNodeData's
            constructor.
        """
        super(UserField, self).__init__(
            repr, doc, type, access_needs_incref=access_needs_incref,
            internal_name=internal_name
        )
        self._is_public = public

    concrete = True


class BuiltinField(UserField):
    """
    A built-in field is just like a UserField, except that its name has no
    prefix. It is disregarded by the parsing machinery too. It is typically
    used for fields on the root node that don't really exist/are added
    manually.
    """

    prefix = None

    def __init__(self, *args, **kwargs):
        super(BuiltinField, self).__init__(*args, **kwargs)
        self.should_emit = False


class BaseStructType(CompiledType):
    """
    Base class to share common behavior between StructType and ASTNodeType.
    """

    def __init__(self, name, location, doc, **kwargs):
        """
        See CompiledType.__init__ for a description of arguments.
        """
        kwargs.setdefault('type_repo_name', name.camel)
        if is_keyword(name):
            name = name + names.Name('Node')

        super(BaseStructType, self).__init__(name, location, doc, **kwargs)

    @property
    def py_nullexpr(self):
        return self._py_nullexpr or '{}({})'.format(self.name.camel, ', '.join(
            f.type.py_nullexpr for f in self.get_fields()
        ))


class StructType(BaseStructType):
    """
    POD composite type.
    """

    def __init__(self, name, location, doc, fields, **kwargs):
        """
        :param name: See CompiledType.__init__.

        :param list[(str|names.Name, AbstractNodeData)] fields: List of (name,
            field) for this struct's fields. Inherited fields must not appear
            in this list.
        """
        internal_name = names.Name('Internal') + name
        super(StructType, self).__init__(
            internal_name, location, doc,
            is_ptr=False,
            null_allowed=True,
            nullexpr=(names.Name('No') + name).camel_with_underscores,
            is_ada_record=True,
            exposed=False,
            hashable=True,
            api_name=name,
            type_repo_name=name.camel,
            dsl_name=name.camel,

            **kwargs
        )
        self._init_fields(fields)
        CompiledTypeRepo.struct_types.append(self)

    @property
    def conversion_requires_context(self):
        return any(f.type.conversion_requires_context
                   for f in self.get_fields())

    def add_as_memoization_key(self, context):
        super(StructType, self).add_as_memoization_key(context)
        for f in self.get_fields():
            f.type.add_as_memoization_key(context)

    @property
    def has_equivalent_function(self):
        return any(f.type.has_equivalent_function for f in self.get_fields())

    def require_hash_function(self):
        super(StructType, self).require_hash_function()
        for f in self.get_fields():
            f.type.require_hash_function()

    @property
    def is_refcounted(self):
        return any(f.type.is_refcounted for f in self._fields.values())

    def is_builtin(self):
        """
        Some structs are considered "built-in", which means that either no code
        needs to be emitted for them, either special code will be emitted on a
        special path, and we can omit them from regular code generation.

        :rtype: bool
        """
        return self in (
            # The env metadata struct is emitted separately from the others
            T.env_md,

            # Entity info and the root node's entity type are not emitted as
            # regular types, because they come from the generic instantiation
            # of Langkit_Support.Lexical_Env.
            CompiledTypeRepo.root_grammar_class.entity_info(),
            CompiledTypeRepo.root_grammar_class.entity,
        )

    def c_inc_ref(self, capi):
        """
        Name of the C API function to inc-ref structure value.

        :param langkit.c_api.CAPISettings capi: Settings for the C API.
        :rtype: str
        """
        return capi.get_name(self.name + names.Name('Inc_Ref'))

    def c_dec_ref(self, capi):
        """
        Name of the C API function to dec-ref structure value.

        :param langkit.c_api.CAPISettings capi: Settings for the C API.
        :rtype: str
        """
        return capi.get_name(self.name + names.Name('Dec_Ref'))

    @property
    def emit_c_type(self):
        """
        Return whether to emit a C type for this type.

        This is used to filter out all entity types except the root one. All
        entity types are compatible from an ABI point of view, so this reduces
        the amount of code emitted for them.

        :rtype: bool
        """
        return not self.is_entity_type or self == T.entity

    @property
    def public_record_type(self):
        """
        Name of the Ada record type used to expose this struct in the public
        API.

        :rtype: names.Name
        """
        return self.name + names.Name('Record')

    @property
    def contains_boxed_fields(self):
        """
        Return if at least one field requires boxing in the public API.

        :rtype: bool
        """
        return any(f.type.public_requires_boxing for f in self.get_fields())

    @property
    def to_public_converter(self):
        return names.Name('To_Public') + self.api_name

    @property
    def to_internal_converter(self):
        return names.Name('To_Internal') + self.api_name

    @property
    def exposed_types(self):
        # Entity types are exposed as opaque types, so don't expose their
        # internals.
        return ([] if self.is_entity_type else
                [f.type for f in self.get_fields()])


class EntityType(StructType):
    """
    Subclass of StructType dedicated to entity types.
    """

    def __init__(self, astnode):
        self.astnode = astnode

        name = names.Name('Entity')
        if not self.astnode.is_root_node:
            name += self.astnode.kwless_raw_name

        super(EntityType, self).__init__(
            name, None, None,
            [('node', BuiltinField(self.astnode, doc='The stored AST node')),
             ('info', BuiltinField(self.astnode.entity_info(),
                                   access_needs_incref=True,
                                   doc='Entity info for this node'))],
            introspection_prefix='Node'
        )
        self.is_entity_type = True
        self._element_type = astnode

        if self.astnode.is_root_node:
            # The root entity is always exposed in public APIs. Some things are
            # automatically emitted for all derived types (without checking
            # _exposed), but we also rely on this flag to be set only for
            # entity types that are used in public properties.
            self.exposed = True

            # LexicalEnv.get, which is bound in the AST.C generate package,
            # returns arrays of root node entities, so the corresponding
            # array type must be declared manually there.
            self.should_emit_array_type = False

    @property
    def dsl_name(self):
        return '{}.entity'.format(self.element_type.dsl_name)

    def c_type(self, capi):
        # Emit only one C binding type for entities. They are all ABI
        # compatible, so this reduces the amount of types emitted.
        return CAPIType(capi, 'base_entity')

    @property
    def is_root_type(self):
        """
        Return whether this entity type correspond to the AST node root type.

        :rtype: bool
        """
        return self.astnode.is_root_node

    @property
    def base(self):
        """
        Return the entity type that `self` overrides, or None for the root.

        :rtype: EntityType
        """
        return None if self.is_root_type else self.astnode.base.entity

    @property
    def api_name(self):
        """
        Type name to use in the public API.

        :rtype: names.Name
        """
        return self.astnode.kwless_raw_name

    @property
    def constructor_name(self):
        """
        Name of the internal Ada functions to instantiate this array.

        :rtype: names.Name
        """
        return names.Name('Create') + self.name

    def to_public_expr(self, internal_expr):
        requires_conversions = not self.element_type.is_root_node

        # If needed, convert the input expression to the root bare node
        node_expr = '{}.Node'.format(internal_expr)
        if requires_conversions:
            node_expr = T.root_node.internal_conversion(self.element_type,
                                                        node_expr)

        # Wrap the bare node into a public entity
        result = 'Wrap_Node ({}, {}.Info)'.format(node_expr, internal_expr)

        # If needed, convert the result expression to the appropriate public
        # entity derivation.
        if requires_conversions:
            result += '.As_{}'.format(self.api_name)

        return result

    def to_internal_expr(self, public_expr, context=None):
        return ('({type} ({name}.Internal.Node), {name}.Internal.Info)'
                .format(type=self.element_type.name, name=public_expr))


class ASTNodeType(BaseStructType):
    """
    Type for an AST node.
    """

    def __init__(self, name, location, doc, base, fields,
                 env_spec=None, element_type=None, annotations=None,
                 is_generic_list_type=False, is_abstract=False,
                 is_synthetic=False, has_abstract_list=False,
                 is_enum_node=False, is_bool_node=False, is_token_node=False,
                 dsl_name=None):
        """
        :param names.Name name: Name for this node.

        :param langkit.diagnostics.Location|None location: Location for the
            declaration of this node, if any.

        :param str|None doc: User documentation for this node.

        :param ASTNodeType|None base: ASTNodeType subclass corresponding to the
            base class for this node. None when creating the root node.

        :param list[(str|names.Name, AbstractNodeData)] fields: List of (name,
            field) for this node's fields. Inherited fields must not appear in
            this list.

        :param langkit.envs.EnvSpec|None env_spec: Environment specification
            for this node, if any.

        :param ASTNodeType|None element_type: For root list types, this must be
            the ASTNodeType subclass that this list contains. Must be left to
            None in all other cases.

        :param bool is_generic_list_type: Whether this subclass will
            materialize the generic list type.

        :param bool is_abstract: Whether this node is abstract. Note that this
            can be changed later. This is forced to True for the generic list
            type and for root list types whose element type has the
            `has_abstract_list` attribute set to True.

        :param bool is_synthetic: Whether this node is synthetic. Note that
            this can be changed later.

        :param bool has_abstract_list: Whether the root list type for this node
            must be abstract. Node that this can be changed later, until the
            list type is actually created.

        :param bool is_enum_node: Whether this node comes from the expansion of
            an enum node.

        :param bool is_bool_node: Whether this node is a qualifier coming from
            the expansion of an enum node.

        :param bool is_token_node: Whether this node only materializes a parsed
            token. If so, grammars that produce such nodes must parse only one
            token (.token_start must be equal to .token_end).

        :param str dsl_name: Name used to represent this type at the DSL level.
            Useful to format diagnostics.
        """
        self.raw_name = name
        self.kwless_raw_name = (self.raw_name + names.Name('Node')
                                if is_keyword(self.raw_name) else
                                self.raw_name)

        name = names.Name('Bare') + self.kwless_raw_name
        self.null_constant = names.Name('No') + name

        is_root = base is None
        is_root_list = not is_root and base.is_generic_list_type
        is_list = not is_root and (is_root_list or base.is_list_type)

        if is_root_list:
            assert element_type.is_ast_node

            # TODO: at this point, we need to make sure thas
            # element_type.has_abstract_list in the future.
            is_abstract = is_abstract or element_type.has_abstract_list

        else:
            assert element_type is None
            if is_list:
                element_type = base._element_type

        if is_root_list:
            doc = doc or 'List of {}.'.format(element_type.dsl_name)

        super(ASTNodeType, self).__init__(
            name, location, doc,
            is_ptr=True, null_allowed=True, is_ada_record=False,
            is_list_type=is_list, should_emit_array_type=not is_root,

            # Even though bare node types are not exposed, we allow them in
            # public APIs and will (un)wrap them as entities automatically.
            exposed=True,

            is_refcounted=False,
            nullexpr=self.null_constant.camel_with_underscores,
            py_nullexpr='None', element_type=element_type, hashable=True,
            type_repo_name=self.raw_name.camel,

            dsl_name=dsl_name or self.raw_name.camel,
            introspection_prefix='Node'
        )
        self._base = base
        self.is_root_node = is_root
        self.is_generic_list_type = is_generic_list_type
        self.is_root_list_type = is_root_list
        self.is_list = is_list

        # Register this new subclass where appropriate in CompiledTypeRepo
        if is_root:
            CompiledTypeRepo.root_grammar_class = self
        CompiledTypeRepo.astnode_types.append(self)

        # Now we have an official root node type, we can create its builtin
        # fields.
        if is_root:
            fields = self.builtin_properties() + fields
        self._init_fields(fields)

        # Make sure that all user fields for nodes are private
        for _, f in fields:
            with f.diagnostic_context:
                check_source_language(
                    not f.is_user_field or
                    isinstance(f, BuiltinField) or
                    f.is_private,
                    'UserField on nodes must be private'
                )

        # Associate concrete syntax fields to the corresponding abstract ones,
        # if any. Don't bother doing validity checking here: the valide_field
        # pass will take care of it.
        inherited_fields = (self.base.get_abstract_node_data_dict()
                            if self.base else {})
        for f_n, f_v in self._fields.items():
            base_field = inherited_fields.get(f_n)
            if isinstance(f_v, Field):
                if (
                    base_field and
                    isinstance(base_field, Field) and
                    base_field.abstract
                ):
                    f_v.overriding = base_field
                    # Null fields are not initialized with a type, so they must
                    # inherit their type from the abstract field they override.
                    if f_v.null:
                        f_v._type = base_field._type
                else:
                    f_v.overriding = None

        from langkit.dsl import Annotations
        annotations = annotations or Annotations()
        self.annotations = annotations
        self.annotations.process_annotations(self, is_root)

        if env_spec:
            env_spec.ast_node = self

        self.env_spec = env_spec
        """
        EnvSpec instance corresponding to this node.
        :type: langkit.compiled_types.EnvSpec|None
        """

        # List types are resolved by construction: we create list types to
        # contain specific ASTNodeType subclasses. All other types are not
        # resolved, only the grammar will resolve them..
        self.is_type_resolved = is_list

        # By default, ASTNodeType subtypes aren't abstract. The "abstract"
        # decorator may change this attribute later. Likewise for synthetic
        # nodes and nodes whose root list type is abstract.
        self.abstract = is_abstract or is_root or is_generic_list_type
        self.synthetic = is_synthetic

        self.has_abstract_list = has_abstract_list
        """
        Whether the automatically generated list type for this ASTNodeType (the
        "root list type") is abstract.
        :type: bool
        """

        # Prepare the list of subclasses for this node type and, if applicable,
        # register it as a subclass of its base.
        self.subclasses = []
        """
        List of subclasses. Overriden in the root grammar class and its
        children.

        :type: list[ASTNodeType]
        """

        if not is_root:
            base.subclasses.append(self)

        # If this is the root grammar type, create the generic list type name
        self.generic_list_type = None
        """
        Root grammar class subclass. It is abstract, generated automatically
        when the root grammar class is known. All root list types subclass it.
        :type: ASTNodeType|None
        """

        if base is None:
            generic_list_type_name = (
                names.Name.from_camel(annotations.generic_list_type)
                if annotations.generic_list_type else
                (self.kwless_raw_name + names.Name('Base_List'))
            )

            self.generic_list_type = ASTNodeType(
                name=generic_list_type_name, location=None, doc='',
                base=self, fields=[], is_generic_list_type=True,
                is_abstract=True
            )

        self.transform_parsers = []
        """
        List of Transform parsers that produce this node.

        :type: list[langkit.parsers._Transform]
        """

        self.list_element_parsers = [] if is_list else None
        """
        For list nodes, list of parsers that produce list elements. None for
        all other nodes.

        :type: list[langkit.parsers.Parser]
        """

        self.precise_list_element_types = None
        """
        For list nodes, precise set of types that this list can contain.

        :rtype: TypeSet
        """

        self.unparser = None
        """
        Unparser for this node. Computed during the NodesToParsers pass.

        :type: langkit.unparsers.NodeUnparser
        """

        self.is_enum_node = is_enum_node
        self.is_bool_node = is_bool_node
        self.is_token_node = is_token_node

        self.token_kind = None
        """
        If this is a token node and if unparser generation is enabled, this
        must reference the only token kind that this node can be associated to.
        Must be None otherwise.

        :type: langkit.lexer.TokenAction|None
        """

        # Make sure we have one entity type for each AST node type
        entity_type = self.entity
        del entity_type

    @property
    def effective_env_spec(self):
        """
        Return the env spec, for this node, whether it's defined on this node
        or inherited from a parent node.
        """
        return self.env_spec if self.env_spec else (
            self.base.effective_env_spec if self.base else None
        )

    @property
    def doc(self):
        result = super(ASTNodeType, self).doc

        # If this is a list node and that parsers build it, add a precise list
        # of types it can contain: the element type might be too generic.
        if self.is_list and not self.synthetic:
            precise_types = (self.precise_list_element_types
                             .minimal_matched_types)
            if len(precise_types) > 1:
                addition = indent(
                    precise_types_doc(
                        'This list node can contain one of the following'
                        ' nodes:', precise_types),
                    first_line_indentation(result))
                return append_paragraph(result, addition)

        return result

    def repr_name(self):
        """
        Return a name that will be used when serializing this AST node.
        :rtype: str
        """
        # This name is used by pretty printers-like code: we need the
        # "original" node name here, not keyword-escaped ones.
        result = self.annotations.repr_name or self.kwless_raw_name.camel
        return result

    @property
    def public_type(self):
        return self.entity

    def is_builtin(self):
        """
        Some AST nodes are considered "built-in", which means that either no
        code needs to be emitted for them, either special code will be emitted
        on a special path, and we can omit them from regular code generation.

        :rtype: bool
        """
        return self in (
            # The root grammar class and the generic list types are emitted
            # separately from the others.
            CompiledTypeRepo.root_grammar_class,
            CompiledTypeRepo.root_grammar_class.generic_list_type,
        )

    def add_transform(self, parser):
        """
        Register ``parser`` as a Transform parser that creates this node.

        This also registers sub-parsers in node fields and keep track of field
        types, checking for consistencies.

        :param langkit.parsers._Transform parser: Transform parser to register.
        """
        self.transform_parsers.append(parser)

    def add_list_element_parser(self, parser):
        """
        Register ``parser`` as a parser that creates list elements.

        :param langkit.parsers.Parser parser: Parser to register.
        """
        self.list_element_parsers.append(parser)

    def check_inferred_field_types(self):
        """
        Check that inferred field types from the grammar are consistent with
        annotations. If there was no type annotation, use the inferred type to
        assign a type to the parse field.
        """
        for parser in self.transform_parsers:
            # Get parse fields except null ones, as parsers don't contribute to
            # typing these.
            #
            # Parsers cannot build abstract types, and only abstract types can
            # have abstract nodes, so in theory we should not have abstract
            # nodes here.  But at this point this DSL check has not happened
            # yet...
            fields = self.get_parse_fields(
                predicate=lambda f: not f.abstract and not f.null
            )

            parsers = parser.fields_parsers
            types = [p.type for p in parsers]

            # Propagate sub-parsers to fields to let them compute precise types
            for f, p in zip(fields, parsers):
                f.parsers_from_transform.append(p)

            # Typing in the Transform parser is already supposed to check
            # consistency in the DSL.
            assert len(fields) == len(types)

            # TODO: instead of expecting types to be subtypes, we might want to
            # perform type unification (take the nearest common ancestor for
            # all field types). But then again, maybe not, it might be too
            # confusing.
            for field, f_type in zip(fields, types):
                if field.type:
                    check_source_language(
                        f_type.matches(field.type),
                        "Field {} already had type {}, got {}".format(
                            field.qualname, field.type.dsl_name,
                            f_type.dsl_name
                        )
                    )

            # Only assign types if self was not yet typed. In the case where it
            # was already typed, we checked above that the new types were
            # consistent with the already present ones.
            if not self.is_type_resolved:
                self.is_type_resolved = True

                for inferred_type, field in zip(types, fields):

                    # At this stage, if the field has a type, it means that the
                    # user assigned it one originally. In this case we will use
                    # the inferred type for checking only (raising an assertion
                    # if it does not correspond).
                    if field.type:
                        with field.diagnostic_context:
                            check_source_language(
                                # Using matches here allows the user to
                                # annotate a field with a more general type
                                # than the one inferred.
                                inferred_type.matches(field.type),
                                'Expected type {} but type inferenced yielded'
                                ' type {}'.format(
                                    field.type.dsl_name,
                                    inferred_type.dsl_name
                                )
                            )
                    else:
                        field.type = inferred_type

    def compute_precise_fields_types(self):
        if self.is_list:
            # Do not compute precise types twice
            if self.precise_list_element_types:
                return

            # A list node can contain nodes coming from its own parsers, but
            # also from subclasses' parsers.
            self.precise_list_element_types = types = TypeSet()
            for subcls in self.subclasses:
                subcls.compute_precise_fields_types()
                types.update(subcls.precise_list_element_types)
            for p in self.list_element_parsers:
                types.update(p.precise_types)

        else:
            for f in self.get_parse_fields(include_inherited=False):
                f._compute_precise_types()

    def warn_imprecise_field_type_annotations(self):
        # The type of synthetic node fields are not inferred, so there is
        # nothing to do for them.
        if self.synthetic:
            return

        for field in self.get_parse_fields():

            # We want to compare the type annotation to the type that was
            # inferred from the grammar. There is more to do than just
            # comparing the two types since there can be several types that
            # specify the same number of concrete types: think of an abstract
            # type that is subclassed only once. So use type sets to do the
            # comparison, instead.
            common_inferred = field.precise_types.minimal_common_type
            inferred_types = TypeSet([common_inferred])
            field_types = TypeSet([field.type])

            with field.diagnostic_context:
                WarningSet.imprecise_field_type_annotations.warn_if(
                    inferred_types != field_types,
                    'Specified type is {}, but it could be more specific:'
                    ' {}'.format(field.type.dsl_name,
                                 common_inferred.dsl_name)
                )

    def get_inheritance_chain(self):
        """
        Return the chain of ASTNodeType instances following the `base` link as
        a list.  Root-most classes come first.

        :rtype: list[ASTNodeType]
        """
        node = self
        result = []
        while node is not None:
            result.append(node)
            node = node.base
        return reversed(result)

    @staticmethod
    def common_ancestor(*nodes):
        """
        Return the bottom-most common parent AST node for all `nodes` AST
        nodes.

        :param list[ASTNodeType] nodes: List of AST node types for which we
            are looking for the common ancestor.
        :rtype: ASTNodeType
        """
        return list(takewhile(
            lambda a: len(set(a)) == 1,
            zip(*map(ASTNodeType.get_inheritance_chain, nodes))
        ))[-1][0]

    @property
    def base(self):
        """
        Return the base type of this AST node type. This is None for the root
        one.

        :rtype: ASTNodeType|None
        """
        return self._base

    @property
    @memoized
    def concrete_subclasses(self):
        """
        Return the list of all (direct or indirect) subclass types for `self`
        that are not abstract, sorted by hierarchical name. If `self` is not
        abstract, it is included.

        :rtype: list[ASTNodeType]
        """
        result = [] if self.abstract else [self]

        sorted_direct_subclasses = sorted(
            self.subclasses, key=lambda subcls: subcls.hierarchical_name
        )
        for subcls in sorted_direct_subclasses:
            result.extend(subcls.concrete_subclasses)

        return result

    @property
    def ada_kind_range_bounds(self):
        """
        Return the name of the Ada enumerators for the range bounds (first and
        last) of kinds that nodes of this type can have.

        :rtype: (str, str)
        """
        subclasses = self.concrete_subclasses
        return ((subclasses[0].ada_kind_name, subclasses[-1].ada_kind_name)
                if subclasses else
                (self.ada_kind_name, self.ada_kind_name))

    def get_parse_fields(self, predicate=None, include_inherited=True):
        """
        Return the list of all the parse fields `self` has, including its
        parents'.

        :param predicate: Predicate to filter fields if needed.
        :type predicate: None|(Field) -> bool

        :param bool include_inherited: If true, include inheritted fields in
            the returned list. Return only fields that were part of the
            declaration of this node otherwise.

        :rtype: list[Field]
        """
        result = self.get_abstract_node_data(predicate, include_inherited,
                                             field_class=Field)
        return result

    def fields_with_accessors(self):
        """
        Return a list of fields for which we must generate accessors in APIs.

        This list excludes inherited/overriden fields so that they are not
        generated multiple times. This list also excludes private fields unless
        the context requires them to be public in the generated library.
        """
        return [f
                for f in self.get_abstract_node_data(
                    include_inherited=False,
                    predicate=lambda f: f.is_public
                )
                if not f.is_overriding]

    def c_type(self, c_api_settings):
        return CAPIType(c_api_settings, 'base_node')

    @property
    @memoized
    def hierarchical_name(self):
        """
        Return a name that contains all the base classes for this node type.

        For instance, if C derives from B which itself derives from A, this
        returns "A.B.C".

        :rtype: str
        """
        return '.'.join(node.name.base_name
                        for node in self.get_inheritance_chain())

    @property
    def ada_kind_name(self):
        """
        Return the name of the Ada enumerator to represent this kind of node.
        :rtype: str
        """
        return (get_context().lang_name +
                self.kwless_raw_name).camel_with_underscores

    @property
    def ada_kind_range_name(self):
        """
        Return the name of the Ada kind subtype to represent the set of node
        kinds that include `self` and all its subclasses.

        :rtype: str
        """
        if self.abstract:
            return self.ada_kind_name
        else:
            return self.ada_kind_name + '_Range'

    @property
    def equivalent_to_root(self):
        """
        Return whether this node type is equivalent to the root type.

        For instance, if the root node has only one subclass, then this
        subclass is equivalent to the root type, as all concrete nodes belong
        to both types.

        This property is useful to avoid emitting tautological kind checks
        during code generation.

        :rtype: bool
        """
        return self.is_root_node or TypeSet({self}) == TypeSet({T.root_node})

    @property
    def introspection_simple_name(self):
        """
        Return the name of the Ada enumeration to represent this node type in
        the introspection API.

        :rtype: str
        """
        return (self.kwless_raw_name
                + names.Name('Type_Id')).camel_with_underscores

    @property
    def introspection_name(self):
        """
        Like `introspection_simple_name`, but with the `Common.` name prefix to
        avoid ambiguities in generated code.

        :rtype: str
        """
        return 'Common.{}'.format(self.introspection_simple_name)

    def value_type_name(self):
        """
        Return the name of the Ada type for the record that implements this AST
        node. The main type name designates the class-wide access to this
        record.

        :rtype: str
        """
        return (self.name + names.Name('Type')).camel_with_underscores

    # We want structural equality on lists whose elements have the same types.
    # Memoization is one way to make sure that, for each CompiledType instance
    # X: X.list is X.list.
    @property
    @memoized
    def list(self):
        """
        Return an ASTNodeType subclass that represent a list of `self`.

        :rtype: CompiledType
        """
        result = ASTNodeType(
            name=self.kwless_raw_name + names.Name('List'),
            location=None, doc='',
            base=CompiledTypeRepo.root_grammar_class.generic_list_type,
            fields=[], element_type=self,
            dsl_name='{}.list'.format(self.dsl_name)
        )

        ctx = get_context(True)
        if ctx:
            ctx.list_types.add(result._element_type)
        else:
            CompiledTypeRepo.pending_list_types.append(result)

        return result

    def entity_info(self):
        """
        Return the entity info type, which is a record that contains semantic
        information which, when added to an AST node, makes an entity.
        """
        # This is manual memoization. It is necessary because memoization does
        # not play well with class method when we want the memoization to be
        # common to the whole class hierarchy.
        if not CompiledTypeRepo.entity_info:
            CompiledTypeRepo.entity_info = StructType(
                names.Name('Entity_Info'), None, None,
                [
                    (names.Name('MD'), BuiltinField(
                        # Use a deferred type so that the language spec. can
                        # reference entity types even before it declared the
                        # metadata class.
                        T.defer_env_md,
                        doc='The metadata associated to the AST node'
                    )),
                    ('rebindings', BuiltinField(T.EnvRebindings,
                                                access_needs_incref=True,
                                                doc="")),
                    ('from_rebound', BuiltinField(T.Bool, doc=""))
                ],
            )
        return CompiledTypeRepo.entity_info

    @property
    @memoized
    def entity(self):
        """
        Return the entity type, which is a node type with assorted semantic
        information.
        """
        return EntityType(self)

    def validate_fields(self):
        """
        Perform various checks on this ASTNodeType's fields.

        In particular, make sure:
        * the AST node is type resolved (i.e. all fields have a type);
        * all fields are AST nodes themselves;
        * it does not hold homonym parse fields.

        Emit errors when appropriate.
        """
        parse_fields = self.get_parse_fields()

        # Consider that AST nodes with type annotations for all their fields
        # are type resolved: they don't need to be referenced by the grammar.
        self.is_type_resolved = (
            self.is_type_resolved
            or all(f.type is not None for f in parse_fields)
        )
        with self.diagnostic_context:
            check_source_language(
                self.is_type_resolved,
                'Unresolved ASTNode subclass. Use it in the grammar or provide'
                ' a type annotation for all its fields'
            )

        for f in parse_fields:
            with f.diagnostic_context:
                # All syntax fields must be nodes
                check_source_language(
                    f.type.is_ast_node,
                    'AST node parse fields must all be AST node themselves.'
                    ' Here, field type is {}'.format(f.type.dsl_name)
                )

                # Null fields must override an abstract one
                check_source_language(
                    not f.null or f.overriding,
                    'Null fields can only be used to override abstract fields',
                    severity=Severity.non_blocking_error
                )

        # Unless the special case of inheritted abstract fields/properties,
        # reject fields which are homonym with inherited fields.
        inherited_fields = (self.base.get_abstract_node_data_dict()
                            if self.base else {})

        # Also check that concrete nodes with not-overriden abstract fields
        abstract_fields = {f_n: f_v for f_n, f_v in inherited_fields.items()
                           if isinstance(f_v, Field) and f_v.abstract}

        for f_n, f_v in self._fields.items():
            with f_v.diagnostic_context:
                f_v_abstract_field = isinstance(f_v, Field) and f_v.abstract
                if f_v_abstract_field:
                    abstract_fields[f_v.name.lower] = f_v

                homonym_fld = inherited_fields.get(f_n)
                if not homonym_fld:
                    continue

                if f_v.is_property:
                    check_source_language(
                        homonym_fld.is_property,
                        'The {} property cannot override {} as the latter is'
                        ' not a property'.format(f_v.qualname,
                                                 homonym_fld.qualname),
                        severity=Severity.non_blocking_error
                    )
                elif (
                    isinstance(f_v, Field) and
                    not f_v.abstract and
                    isinstance(homonym_fld, Field) and
                    homonym_fld.abstract
                ):
                    check_source_language(
                        f_v.type.matches(homonym_fld.type),
                        'Type of overriding field ({}) does not match type of'
                        ' abstract field ({})'
                        .format(f_v.type.dsl_name, homonym_fld.type.dsl_name),
                        severity=Severity.non_blocking_error
                    )
                else:
                    check_source_language(
                        False,
                        '{} cannot override {} unless the former is a concrete'
                        ' field and the latter is an abstract one'
                        .format(f_v.qualname, homonym_fld.qualname),
                        severity=Severity.non_blocking_error
                    )

                if f_n in abstract_fields:
                    abstract_fields.pop(f_n)

        with self.diagnostic_context:
            check_source_language(
                self.abstract or not abstract_fields,
                'This node is concrete, yet it has abstract fields that are'
                ' not overriden: {}'.format(', '.join(sorted(
                    f.qualname for f in abstract_fields.values()
                ))),
                severity=Severity.non_blocking_error
            )

    def builtin_properties(self):
        """
        Return properties available for all AST nodes.

        Note that CompiledTypeRepo.root_grammar_class must be defined
        first.

        :rtype: list[(str, AbstractNodeData)]
        """
        from langkit.expressions import PropertyDef

        # Note that we must not provide implementation for them here (no
        # expression) since the implementation comes from the hard-coded root
        # AST node type definition.
        return [
            # The following fields return lexical env values, which are
            # ref-counted. However these specific envs are owned by the
            # analysis unit, so they are not ref-counted.

            ('node_env', PropertyDef(
                expr=None, prefix=None, type=T.LexicalEnv, public=False,
                external=True, uses_entity_info=True, uses_envs=True,
                optional_entity_info=True, warn_on_unused=False,
                doc='For nodes that introduce a new environment, return the'
                    ' parent lexical environment. Return the "inherited"'
                    ' environment otherwise.'
            )),
            ('children_env', PropertyDef(
                expr=None, prefix=None, type=T.LexicalEnv, public=False,
                external=True, uses_entity_info=True, uses_envs=True,
                optional_entity_info=True, warn_on_unused=False,
                doc='For nodes that introduce a new environment, return it.'
                    ' Return the "inherited" environment otherwise.'
            )),

            ('parent', PropertyDef(
                expr=None, prefix=None, type=T.entity, public=True,
                external=True, uses_entity_info=True, uses_envs=False,
                warn_on_unused=False,
                doc='Return the lexical parent for this node. Return null for'
                    ' the root AST node or for AST nodes for which no one has'
                    ' a reference to the parent.'
            )),

            # The following builtin fields are implemented as a property, so
            # there is no need for an additional inc-ref.
            ('parents', PropertyDef(
                expr=None, prefix=None, type=T.entity.array, public=True,
                external=True, uses_entity_info=True, uses_envs=False,
                warn_on_unused=False,
                doc='Return an array that contains the lexical parents (this'
                    ' node included). Nearer parents are first in the list.'
            )),
            ('children', PropertyDef(
                expr=None, prefix=None, type=T.entity.array, public=True,
                external=True, uses_entity_info=True, uses_envs=False,
                warn_on_unused=False,
                doc='Return an array that contains the direct lexical'
                    ' children.'
            )),
            ('token_start', PropertyDef(
                expr=None, prefix=None, type=T.Token,
                public=True, external=True, uses_entity_info=False,
                uses_envs=False,
                doc='Return the first token used to parse this node.'
            )),
            ('token_end', PropertyDef(
                expr=None, prefix=None, type=T.Token,
                public=True, external=True, uses_entity_info=False,
                uses_envs=False,
                doc='Return the last token used to parse this node.'
            )),
            ('child_index', BuiltinField(
                type=T.Int,
                doc="Return the 0-based index for Node in its parent's"
                    " children."
            )),
            ('previous_sibling', PropertyDef(
                expr=None, prefix=None, type=T.entity, public=True,
                external=True, uses_entity_info=True, uses_envs=False,
                warn_on_unused=False,
                doc="Return the node's previous sibling, if there is one."
            )),
            ('next_sibling', PropertyDef(
                expr=None, prefix=None, type=T.entity, public=True,
                external=True, uses_entity_info=True, uses_envs=False,
                warn_on_unused=False,
                doc="Return the node's next sibling, if there is one."
            )),
            ('unit', PropertyDef(
                expr=None, prefix=None, type=T.AnalysisUnit, public=True,
                external=True, uses_entity_info=False, uses_envs=False,
                warn_on_unused=False,
                doc='Return the analysis unit owning this node.'
            )),
            ('is_ghost', PropertyDef(
                expr=None, prefix=None, type=T.Bool, public=True,
                external=True, uses_entity_info=False, uses_envs=False,
                warn_on_unused=False,
                doc="""
                Return whether the node is a ghost.

                Unlike regular nodes, ghost nodes cover no token in the input
                source: they are logically located instead between two tokens.
                The "token_first" of all ghost nodes is the token right after
                this logical position, while they have no "token_last".
                """
            )),

            ('text', PropertyDef(
                lambda: None,
                prefix=None, type=T.String, public=False,
                external=True, uses_entity_info=False,
                uses_envs=True, warn_on_unused=False, doc="""
                Return the text corresponding to this node. Private property
                (for internal DSL use).
                """
            )),
        ]

    def snaps(self, anchor_end):
        """
        Whether this node type snaps. To see what this means, see
        langkit.dsl.Annotations documentation.

        Note that no node snaps if unparsers are not requested.

        :param bool anchor_end: If true, return whether this node snaps at the
            end, otherwise return whether it snaps at the beginning.
        :rtype: bool
        """
        from langkit.unparsers import RegularNodeUnparser

        unparser = self.unparser
        i = -1 if anchor_end else 0

        # Unless this node is specifically tagged as snapping, consider it does
        # not snap as soon as it has no unparser (which happens when unparsers
        # are disabled or for abstract nodes) or when it's a list or a token
        # node.
        if self.annotations.snaps:
            return True
        if unparser is None or not isinstance(unparser, RegularNodeUnparser):
            return False

        # This is a regular node with no specific "snaps" annotation, so it
        # snaps if the (un)parser has no leading/training token (optional or
        # not) and if the node for the first/last field snaps itself.
        #
        # And by default, nodes without fields don't snap.
        if not unparser.field_unparsers:
            return False
        field_unparser = unparser.field_unparsers[i]

        anchor_node_tokens = (unparser.post_tokens
                              if anchor_end else unparser.pre_tokens)
        field_node_tokens = (field_unparser.post_tokens
                             if anchor_end else field_unparser.pre_tokens)
        return (not anchor_node_tokens and
                not field_node_tokens and
                field_unparser.field.type.snaps(anchor_end))

    @property
    def snaps_at_start(self):
        return self.snaps(False)

    @property
    def snaps_at_end(self):
        return self.snaps(True)

    def to_public_expr(self, internal_expr):
        result = 'Wrap_Node ({}, {})'.format(internal_expr,
                                             T.entity_info.nullexpr)
        if not self.is_root_node:
            result += '.As_{}'.format(self.entity.api_name)
        return result

    def to_internal_expr(self, public_expr, context=None):
        return ('{type} ({name}.Internal.Node)'
                .format(type=self.name, name=public_expr))

    def internal_converter(self, from_type):
        """
        Return the name of the converter from bare nodes of type `from_type` to
        bare nodes of type `self`.

        Note that only conversions to or from the root node are supported.

        :rtype: str
        """
        if self.is_root_node:
            assert not from_type.is_root_node
            return 'Convert_From_{}'.format(from_type.kwless_raw_name)
        elif from_type.is_root_node:
            return 'Convert_To_{}'.format(self.kwless_raw_name)
        else:
            assert False

    def internal_conversion(self, expr_type, expr):
        """
        Ada code generation helper to convert bare nodes.

        :param ASTNodeType|EntityType expr_type: Static type for `expr`'s
            result. For convenience, entity types are accepted and interpreted
            as the bare node they wrap.
        :param str expr: Expression that returns a bare node.
        :return str: Expression that returns a node whose `self` is the type.
        """
        if expr_type.is_entity_type:
            expr_type = expr_type.element_type

        # Avoid useless conversions
        if self == expr_type:
            return expr

        root_node_expr = (
            expr
            if expr_type.is_root_node else
            '{} ({})'.format(T.root_node.internal_converter(expr_type), expr))

        return (root_node_expr
                if self.is_root_node else
                '{} ({})'.format(self.internal_converter(T.root_node),
                                 root_node_expr))


# We tag the ASTNodeType class as abstract here, because of the circular
# dependency between the @abstract decorator and the ASTNodeType class, which
# is caused by the assert statement that is inside the decorator.
ASTNodeType.abstract = True


class ArrayType(CompiledType):
    """
    Base class for array types.
    """

    def __init__(self, name, element_type):
        self.null_constant = names.Name('No') + name

        # By default, array types are not exposed. A compilation pass will tag
        # only the ones that are exposed through the public API.
        super(ArrayType, self).__init__(
            name=name, is_ptr=True,
            is_refcounted=True,
            nullexpr=self.null_constant.camel_with_underscores,
            element_type=element_type,
            null_allowed=True,
            has_equivalent_function=True)
        CompiledTypeRepo.array_types.add(self)

        # Text_Type is always defined, since it comes from
        # Langkit_Support.Text. To avoid discrepancies in code generation,
        # consider it is always exposed.
        if self.is_string_type:
            self.exposed = True

    @property
    def name(self):
        return self.element_type.name + names.Name('Array_Access')

    @property
    def api_name(self):
        """
        Name of the public array type. This is the same as `array_type_name`
        for public types (such as booleans, integers, analysis units, etc.) but
        we have a different one for "wrapped" types, such as entities.
        """
        return (names.Name('Text_Type')
                if self.is_string_type else
                self.element_type.api_name + names.Name('Array'))

    @property
    def api_access_name(self):
        """
        Name of the access type for public arrays. Used as internals for
        array struct fields.

        :rtype: names.Name
        """
        return self.api_name + names.Name('Access')

    @property
    def constructor_name(self):
        """
        Name of the internal Ada functions to instantiate this array.

        :rtype: names.Name
        """
        return (names.Name('Create') +
                self.element_type.name +
                names.Name('Array'))

    @property
    def dsl_name(self):
        return '{}.array'.format(self.element_type.dsl_name)

    @property
    def array_type_name(self):
        """
        Name of the Ada array type.

        :rtype: names.Name
        """
        return (self.api_name
                if self.is_string_type else
                (names.Name('Internal') +
                    self.element_type.name +
                    names.Name('Array')))

    @property
    def pointed(self):
        """
        Name of the type for values that are pointed to by general values.

        :rtype: names.Name
        """
        return self.element_type.name + names.Name('Array_Record')

    @property
    def pkg_vector(self):
        """
        Name of the Langkit_Support.Vectors package instantiation corresponding
        to this element_type.

        :rtype: names.Name
        """
        return self.element_type.name + names.Name('Vectors')

    def c_type(self, c_api_settings):
        if (self.element_type.is_entity_type and
                not self.element_type.emit_c_type):
            return T.entity.array.c_type(c_api_settings)
        else:
            return CAPIType(c_api_settings, self.api_name)

    def index_type(self):
        """
        Name of the index type for this array type.

        :rtype: str
        """
        pkg_vector_name = self.element_type.name + names.Name('Vectors')
        return '{}.Index_Type'.format(pkg_vector_name.camel_with_underscores)

    def vector(self):
        """
        Name of the type for vector values.

        :rtype: names.Name
        """
        return names.Name(self.pkg_vector.camel_with_underscores + '.Vector')

    def c_create(self, capi):
        """
        Name of the C API function to create an array value.

        :param langkit.c_api.CAPISettings capi: Settings for the C API.
        :rtype: str
        """
        return capi.get_name(self.api_name + names.Name('Create'))

    def c_inc_ref(self, capi):
        """
        Name of the C API function to inc-ref an array value.

        :param langkit.c_api.CAPISettings capi: Settings for the C API.
        :rtype: str
        """
        return capi.get_name(self.api_name + names.Name('Inc_Ref'))

    def c_dec_ref(self, capi):
        """
        Name of the C API function to dec-ref an array value.

        :param langkit.c_api.CAPISettings capi: Settings for the C API.
        :rtype: str
        """
        return capi.get_name(self.api_name + names.Name('Dec_Ref'))

    @property
    def py_converter(self):
        """
        Name of the Python class used to convert back and forth between
        user-facing values (lists) and C API values (pointers to array
        records).

        :rtype: str
        """
        return '_{}Converter'.format(self.api_name.camel)

    @property
    def conversion_requires_context(self):
        return self.element_type.conversion_requires_context

    @property
    def to_public_converter(self):
        return names.Name('To_Public') + self.api_name

    @property
    def to_internal_converter(self):
        return names.Name('To_Internal') + self.api_name

    @property
    def emit_c_type(self):
        """
        Return whether to emit a C type for this type.

        See StructType.emit_c_type.

        :rtype: bool
        """
        return (not self.element_type.is_struct_type or
                self.element_type.emit_c_type)

    @property
    def public_requires_boxing(self):
        return True

    @property
    def exposed_types(self):
        return [self.element_type]


class EnumType(CompiledType):
    """
    Ada-like enumeration type.
    """

    def __init__(self, name, location, doc, value_names):
        """
        :type value_names: list[name.Names]
        """
        super(EnumType, self).__init__(
            name, location, doc, is_ptr=False, exposed=True,
            null_allowed=False, hashable=True)

        self.values = [EnumValue(self, vn, i)
                       for i, vn in enumerate(value_names)]

        self.values_dict = {v.name: v for v in self.values}
        """
        Lookup dictionnary for enumeration values, by name.

        :type: dict[names.Name: EnumValue]
        """

        CompiledTypeRepo.enum_types.append(self)

    @property
    def py_helper(self):
        """
        Name of the class helper in the Python binding layer to convert values
        for this enumeration back and forth between C and Python-level values.

        :rtype: str
        """
        return self.api_name.camel

    def resolve_value(self, value_name):
        """
        Return an abstract expression corresponding to the given value name.

        :param str value_name: Lower-case name of the value to process.
        :rtype: langkit.expressions.AbstractExpression
        """
        return (self.values_dict[names.Name.from_lower(value_name)]
                .to_abstract_expr)


class EnumValue(object):
    """
    Possible value for an enumeration type.
    """

    def __init__(self, enum_type, name, index):
        self.type = enum_type
        """
        Enumeration type that owns this enumeration value.

        :type: EnumType
        """

        self.name = name
        """
        Name for this enumeration value.

        :type: names.Name
        """

        self.index = index
        """
        Index for this enumeration value. Each enumeration values in a given
        enumeration type are assigned an index, incrementing from 0.

        :type: int
        """

    @property
    def dsl_name(self):
        """
        Return the DSL name for this enumeration value.

        :rtype: str
        """
        return '{}.{}'.format(self.type.dsl_name, self.name.camel)

    @property
    def ada_name(self):
        """
        Return the identifier used in Ada to designate this value.

        :rtype: str
        """
        return self.name.camel_with_underscores

    def c_name(self, c_api_settings):
        """
        Return the identifier used in C to designate this value.

        :param CAPISettings c_api_settings: The settings for the C API.
        :rtype: str
        """
        return '{}_{}'.format(c_api_settings.symbol_prefix.upper(),
                              (self.type.name + self.name).upper)

    @property
    def to_abstract_expr(self):
        """
        Create an abstract expression wrapping this enumeration value.

        :rtype: langkit.expressions.AbstractExpression
        """
        from langkit.expressions import EnumLiteral
        return EnumLiteral(self)


class BigIntegerType(CompiledType):
    def __init__(self):
        super(BigIntegerType, self).__init__(
            'BigIntegerType',
            dsl_name='BigInt',
            exposed=True,
            nullexpr='No_Big_Integer',
            is_refcounted=True,
            has_equivalent_function=True,
            is_ada_record=True,
            c_type_name='big_integer',
            api_name='BigInteger')

    @property
    def to_public_converter(self):
        return 'Create_Public_Big_Integer'

    @property
    def to_internal_converter(self):
        return 'Create_Big_Integer'


class AnalysisUnitType(CompiledType):
    def __init__(self):
        from langkit.expressions import PropertyDef

        super(AnalysisUnitType, self).__init__(
            'InternalUnit',
            exposed=True,
            nullexpr='null',
            should_emit_array_type=True,
            null_allowed=True,
            hashable=True,
            c_type_name='analysis_unit',
            api_name='AnalysisUnit',
            dsl_name='AnalysisUnit')

        root_field = BuiltinField(
            T.defer_root_node,
            doc='Return the root node of this unit.',
            internal_name=names.Name('AST_Root'))

        self._init_fields([
            ('root', root_field),
            ('is_referenced_from', PropertyDef(
                lambda unit=T.AnalysisUnit: None,
                prefix=None, type=T.Bool, public=False,
                external=True, uses_entity_info=False,
                uses_envs=True, warn_on_unused=False,
                doc='Return whether this unit is referenced from ``unit``.'
            )),
        ])

    @property
    def to_public_converter(self):
        return 'Wrap_Unit'

    @property
    def to_internal_converter(self):
        return 'Unwrap_Unit'


class SymbolType(CompiledType):
    def __init__(self):
        from langkit.expressions import PropertyDef

        super(SymbolType, self).__init__(
            'SymbolType',
            dsl_name='Symbol',
            introspection_prefix='Unbounded_Text',
            exposed=True,
            nullexpr='null',
            null_allowed=True,

            # See below: symbols are represented in the C API as text records
            is_ada_record=True,
            c_type_name='symbol_type',
            api_name='UnboundedTextType',
            hashable=True,
            conversion_requires_context=True)

        self._init_fields([
            ('image', PropertyDef(
                lambda: None,
                prefix=None, type=T.String, public=False,
                external=True, uses_entity_info=False,
                uses_envs=True, warn_on_unused=False,
                doc='Return this symbol as a string'
            )),
        ])

    def to_public_expr(self, internal_expr):
        return 'To_Unbounded_Text (Image ({}))'.format(internal_expr)

    def to_internal_expr(self, public_expr, context):
        return 'Lookup_Symbol ({}, To_Text ({}))'.format(context, public_expr)


def create_builtin_types():
    """
    Create CompiledType instances for all built-in types. This will
    automatically register them in the current CompiledTypeRepo.
    """
    AnalysisUnitType()

    EnumType(name='AnalysisUnitKind',
             location=None,
             doc="""
             Specify a kind of analysis unit. Specification units provide an
             interface to the outer world while body units provide an
             implementation for the corresponding interface.
             """,
             value_names=[names.Name('Unit_Specification'),
                          names.Name('Unit_Body')])

    EnumType(name='LookupKind',
             location=None,
             doc="""
             """,
             value_names=[names.Name('Recursive'),
                          names.Name('Flat'),
                          names.Name('Minimal')])
    lex_env_type = CompiledType(
        'LexicalEnv',
        nullexpr='Empty_Env',
        should_emit_array_type=False,
        null_allowed=True,
        is_ptr=False,
        is_refcounted=True,
        py_nullexpr='LexicalEnv.Empty',
        hashable=True,
        has_equivalent_function=True,
    )

    LogicVarType()

    CompiledType(
        'LogicEquation',
        dsl_name='Equation',
        nullexpr='Null_Logic_Equation',
        null_allowed=False,
        c_type_name='equation_type',
        is_refcounted=True,
    )

    rebindings = EnvRebindingsType()
    rebindings_parent_field = BuiltinField(
        rebindings, doc='Return the parent rebindings for ``rebindings``.',
        internal_name=names.Name('Parent'))

    rebindings._init_fields([
        ('old_env', BuiltinField(
            lex_env_type,
            doc="""
            Return the lexical environment that is remapped by ``rebindings``.
            """
        )),
        ('new_env', BuiltinField(
            lex_env_type, doc="""
            Return the lexical environment that ``rebindings`` remaps to.
            """
        )),
        ('get_parent', rebindings_parent_field),
    ])

    CompiledType(
        name='Boolean',
        dsl_name='Bool',
        exposed=True,
        is_ptr=False,
        nullexpr='False',
        null_allowed=True,
        py_nullexpr='False',
        hashable=True,

        # "bool" is not a built-in type in C: we define our own type based on
        # uint8_t.
        c_type_name='bool'
    )

    CompiledType(
        name='Integer',
        dsl_name='Int',
        exposed=True,
        is_ptr=False,
        nullexpr='0',
        external=True,
        c_type_name='int',
        hashable=True,
    )

    CompiledType(
        'SourceLocationRange',
        exposed=True,
        is_ptr=False,
        nullexpr='SourceLocationRange()',
    )

    TokenType()
    SymbolType()
    BigIntegerType()

    CompiledType('CharacterType',
                 dsl_name='Character',
                 introspection_prefix='Character',
                 exposed=True,
                 nullexpr="Chars.NUL",
                 c_type_name='uint32_t',
                 external=True,
                 api_name='CharacterType')


class TypeRepo(object):
    """
    Repository of types. Used to be able to do early references to not yet
    declared types, in this fashion::

        T = TypeRepo()

        class A(ASTNode):
            p = AbstractProperty(type=T.B)

        class B(ASTNode):
            pass

    Only Struct and AST node types are reachable through the type repository.
    """

    class Defer(object):
        """
        Internal class representing a not-yet resolved type.
        """
        def __init__(self, getter, label):
            """
            :param () -> CompiledType getter: A function that will return
                the resolved type when called.
            :param str label: Short description of what this Defer object
                resolves to, for debugging purposes.
            """
            self.getter = getter
            self.label = label

        def get(self):
            """
            Resolve the internally referenced type.

            :rtype: CompiledType
            """
            return self.getter()

        def __getattr__(self, name):
            def get():
                prefix = self.get()
                if (
                    name in ('array', 'list', 'entity', 'new')
                    or not isinstance(prefix, BaseStructType)
                ):
                    return getattr(prefix, name)

                try:
                    return prefix._fields[name]
                except KeyError:
                    check_source_language(
                        False,
                        '{prefix} has no {attr} attribute'.format(
                            prefix=(prefix.dsl_name
                                    if isinstance(prefix, CompiledType) else
                                    prefix),
                            attr=repr(name)
                        )
                    )
            return TypeRepo.Defer(get, '{}.{}'.format(self.label, name))

        def __call__(self, *args, **kwargs):
            label_args = []
            for arg in args:
                label_args.append(str(arg))
            for kw, arg in kwargs.items():
                label_args.append('{}={}'.format(kw, arg))

            return TypeRepo.Defer(
                lambda: self.get()(*args, **kwargs),
                '{}({})'.format(self.label, ', '.join(label_args))
            )

        def __repr__(self):
            return '<Defer {}>'.format(self.label)

    def __getattr__(self, type_name):
        """
        Build and return a Defer type that references the above type.

        :param str type_name: The name of the rule.
        """
        type_dict = CompiledTypeRepo.type_dict

        def resolve():
            try:
                return type_dict[type_name]
            except KeyError:
                close_matches = difflib.get_close_matches(type_name, type_dict)
                check_source_language(
                    False,
                    'Invalid type name: {}{}'.format(
                        type_name,
                        ', did you one of the following? {}'.format(
                            ', '.join(close_matches)
                        ) if close_matches else ''
                    )
                )

        # Resolve immediately the type reference if possible, except for AST
        # nodes: use a Defer object anyway so that we can support properties
        # reference on top of it.
        result = type_dict.get(type_name)
        return (TypeRepo.Defer(resolve, type_name)
                if result is None or isinstance(result, ASTNodeType) else
                result)

    @property
    def root_node(self):
        """
        Shortcut to get the root AST node.
        :rtype: ASTNodeType
        """
        result = CompiledTypeRepo.root_grammar_class
        assert result
        return result

    @property
    def defer_root_node(self):
        return self.Defer(lambda: self.root_node, 'root_node')

    @property
    def env_md(self):
        """
        Shortcut to get the lexical environment metadata type.
        :rtype: StructType
        """
        assert CompiledTypeRepo.env_metadata is not None
        return CompiledTypeRepo.env_metadata

    @property
    def defer_env_md(self):
        return self.Defer(lambda: self.env_md, '.env_md')

    @property
    def entity_info(self):
        """
        Shortcut to get the entity information type.
        :rtype: StructType
        """
        return CompiledTypeRepo.root_grammar_class.entity_info()

    @property
    def entity(self):
        """
        This property returns the root type used to describe an AST node with
        semantic information attached.
        """
        return self.root_node.entity

    @property
    @memoized
    def env_assoc(self):
        """
        EnvAssoc type, used to add associations of key and value to the lexical
        environments, via the add_to_env primitive.
        """
        return StructType(
            names.Name('Env_Assoc'), None, None,
            [('key', UserField(type=T.Symbol)),
             ('val', UserField(type=self.defer_root_node)),
             ('dest_env', UserField(type=T.LexicalEnv)),
             ('metadata', UserField(type=self.defer_env_md))]
        )

    @property
    def String(self):
        """
        Shortcut for Character.array.
        """
        return self.Character.array


def resolve_type(typeref):
    """
    Resolve a type reference to the actual CompiledType instance.

    :param typeref: Type reference to resolve. It can be either:

        * None: it is directly returned;
        * a CompiledType instance: it is directly returned;
        * a TypeRepo.Defer instance: it is deferred;
        * a DSLType subclass: the corresponding CompiledType instance is
          retrieved;
        * an _EnumNodeAlternative instance: the type corresponding to this
          alternative is retrieved.

    :rtype: CompiledType
    """
    from langkit.dsl import DSLType, _EnumNodeAlternative

    if typeref is None or isinstance(typeref, CompiledType):
        result = typeref

    elif isinstance(typeref, TypeRepo.Defer):
        result = typeref.get()

    elif issubtype(typeref, DSLType):
        result = typeref._resolve()

    elif isinstance(typeref, _EnumNodeAlternative):
        result = typeref.type

    else:
        check_source_language(False,
                              'Invalid type reference: {}'.format(typeref))

    assert result is None or isinstance(result, CompiledType)
    return result


T = TypeRepo()
"""
Default type repository instance, to be used to refer to a type before its
declaration
"""

create_builtin_types()
