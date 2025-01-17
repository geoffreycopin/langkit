## vim: filetype=makoada

with Ada.Containers.Hashed_Maps;
with Ada.Strings.Unbounded; use Ada.Strings.Unbounded;
with Ada.Strings.Unbounded.Hash;

with Langkit_Support.Text;    use Langkit_Support.Text;

with ${ada_lib_name}.Implementation; use ${ada_lib_name}.Implementation;
with ${ada_lib_name}.Common;         use ${ada_lib_name}.Common;

private package ${ada_lib_name}.Introspection_Implementation is

   ------------------------
   -- Polymorphic values --
   ------------------------

   --  TODO: for now, support only value types that are required to represent
   --  default values for property arguments.

   subtype Internal_Value_Kind is Any_Value_Kind
      with Static_Predicate => Internal_Value_Kind in
         None | Boolean_Value | Integer_Value | Character_Value | Node_Value;

   type Internal_Value (Kind : Internal_Value_Kind := None) is record
      case Kind is
         when None =>
            null;

         when Boolean_Value =>
            Boolean_Value : Boolean;

         when Integer_Value =>
            Integer_Value : Integer;

         when Character_Value =>
            Character_Value : Character_Type;

         when Node_Value =>
            Node_Value : ${T.entity.name};
      end case;
   end record;

   No_Internal_Value : constant Internal_Value := (Kind => None);

   type Internal_Value_Array is array (Positive range <>) of Internal_Value;

   function As_Boolean (Self : Internal_Value) return Boolean;
   function Create_Boolean (Value : Boolean) return Internal_Value is
     ((Kind => Boolean_Value, Boolean_Value => Value));

   function As_Integer (Self : Internal_Value) return Integer;
   function Create_Integer (Value : Integer) return Internal_Value is
     ((Kind => Integer_Value, Integer_Value => Value));

   function As_Character (Self : Internal_Value) return Character_Type;
   function Create_Character (Value : Character_Type) return Internal_Value is
     ((Kind => Character_Value, Character_Value => Value));

   function As_Node (Self : Internal_Value) return ${T.entity.name};
   function Create_Node (Value : ${T.entity.name}) return Internal_Value is
     ((Kind => Node_Value, Node_Value => Value));

   -----------------------
   -- Descriptor tables --
   -----------------------

   type String_Access is access constant String;
   type String_Array is array (Positive range <>) of String_Access;

   ------------------------------
   -- Syntax field descriptors --
   ------------------------------

   type Syntax_Field_Descriptor (Name_Length : Natural) is record
      Field_Type : Node_Type_Id;
      Name       : String (1 .. Name_Length);
   end record;
   --  General description of a field (independent of field implementations)

   type Syntax_Field_Descriptor_Access is
      access constant Syntax_Field_Descriptor;

   --  Descriptors for syntax fields

   % for f in ctx.sorted_parse_fields:
      <% name = f._name.lower %>
      Desc_For_${f.introspection_enum_literal} : aliased constant
         Syntax_Field_Descriptor := (
            Name_Length => ${len(name)},
            Field_Type  => ${f.type.introspection_name},
            Name        => ${string_repr(name)}
         );
   % endfor

   Syntax_Field_Descriptors : constant
      array (Field_Reference) of Syntax_Field_Descriptor_Access := (
      % if ctx.sorted_parse_fields:
         ${', '.join("{name} => Desc_For_{name}'Access"
                     .format(name=f.introspection_enum_literal)
                     for f in ctx.sorted_parse_fields)}
      % else:
         Field_Reference => <>
      % endif
   );

   --------------------------
   -- Property descriptors --
   --------------------------

   type Property_Descriptor (
      Name_Length : Natural;
      --  Length of the proprety name

      Arity : Natural
      --  Number of arguments this property takes (exclude the Self argument)
   )
   is record
      Name : String (1 .. Name_Length);
      --  Lower-case name for this property

      Return_Type : Value_Constraint;
      --  Return type for this property

      Argument_Types : Value_Constraint_Array (1 .. Arity);
      --  Types of the arguments that this property takes

      Argument_Names : String_Array (1 .. Arity);
      --  Lower-case names for arguments that this property takes

      Argument_Default_Values : Internal_Value_Array (1 .. Arity);
      --  Default values (if any, otherwise No_Internal_Value) for arguments
      --  that this property takes.
   end record;

   type Property_Descriptor_Access is access constant Property_Descriptor;

   --  Descriptors for properties

   <%
      # First, generate constant for argument names, so that we can refer to
      # them from property descriptors.
      names = set()
      for p in ctx.sorted_properties:
         for arg in p.arguments:
            names.add(arg.name.lower)
   %>
   % for n in sorted(names):
   Name_For_${n} : aliased constant String := ${string_repr(n)};
   % endfor

   % for p in ctx.sorted_properties:
      <% name = p._name.lower %>
      Desc_For_${p.introspection_enum_literal} : aliased constant
         Property_Descriptor := (
            Name_Length => ${len(name)},
            Arity       => ${len(p.arguments)},

            Name => ${string_repr(name)},

            Return_Type    => ${p.type.introspection_constraint},
            Argument_Types => (
               % if p.arguments:
                  ${', '.join('{} => {}'
                              .format(i, arg.type.introspection_constraint)
                              for i, arg in enumerate(p.arguments, 1))}
               % else:
                  1 .. 0 => <>
               % endif
            ),
            Argument_Names => (
               % if p.arguments:
                  ${', '.join("{} => Name_For_{}'Access"
                              .format(i, arg.name.lower)
                              for i, arg in enumerate(p.arguments, 1))}
               % else:
                  1 .. 0 => <>
               % endif
            ),
            Argument_Default_Values => (
               % if p.arguments:
                  ${', '.join('{} => {}'.format(
                     i,
                     'No_Internal_Value'
                     if arg.default_value is None else
                     arg.default_value.render_introspection_constant())
                     for i, arg in enumerate(p.arguments, 1))}
               % else:
                  1 .. 0 => <>
               % endif
            )
         );
   % endfor

   % if ctx.sorted_properties:
      Property_Descriptors : constant
         array (Property_Reference) of Property_Descriptor_Access := (
         % if ctx.sorted_properties:
            ${', '.join("Desc_For_{}'Access"
                        .format(p.introspection_enum_literal)
                        for p in ctx.sorted_properties)}
         % else:
            Property_Reference => <>
         % endif
      );
   % endif

   ---------------------------
   -- Node type descriptors --
   ---------------------------

   type Node_Field_Descriptor (Is_Abstract_Or_Null : Boolean) is record
      Field : Field_Reference;
      --  Reference to the field this describes

      --  Only non-null concrete fields are assigned an index

      case Is_Abstract_Or_Null is
         when False =>
            Index : Positive;
            --  Index for this field

         when True =>
            null;
      end case;
   end record;
   --  Description of a field as implemented by a specific node

   type Node_Field_Descriptor_Access is access constant Node_Field_Descriptor;
   type Node_Field_Descriptor_Array is
      array (Positive range <>) of Node_Field_Descriptor_Access;

   type Node_Type_Descriptor
     (Is_Abstract       : Boolean;
      Derivations_Count : Natural;
      Fields_Count      : Natural;
      Properties_Count  : Natural)
   is record
      Base_Type : Any_Node_Type_Id;
      --  Reference to the node type from which this derives

      Derivations : Node_Type_Id_Array (1 .. Derivations_Count);
      --  List of references for all node types that derives from this

      DSL_Name : Unbounded_String;
      --  Name for this type in the Langkit DSL

      Inherited_Fields : Natural;
      --  Number of syntax field inherited from the base type

      Fields : Node_Field_Descriptor_Array (1 .. Fields_Count);
      --  For regular node types, list of syntax fields that are specific to
      --  this derivation (i.e. excluding fields from the base type).

      Properties : Property_Reference_Array (1 .. Properties_Count);
      --  List of properties that this node provides that are specific to this
      --  derivation (i.e. excluding fields from the base type).

      --  Only concrete nodes are assigned a node kind

      case Is_Abstract is
         when False =>
            Kind : ${root_node_kind_name};
            --  Kind corresponding this this node type

         when True =>
            null;
      end case;
   end record;

   type Node_Type_Descriptor_Access is access constant Node_Type_Descriptor;

   --  Descriptors for node types and their syntax fields

   % for n in ctx.astnode_types:
   <%
      fields = n.get_parse_fields(include_inherited=False)
      properties = n.get_properties(
         predicate=lambda p: p.is_public and not p.overriding,
         include_inherited=False)

      if n.is_root_node:
         inherited_fields = []
      else:
         inherited_fields = n.base.get_parse_fields(
            predicate=lambda f: not (f.abstract or f.null),
            include_inherited=True)
   %>

   % for f in fields:
   ${f.name}_For_${n.kwless_raw_name} : aliased constant Node_Field_Descriptor
   := (
      Is_Abstract_Or_Null => ${f.abstract or f.null},
      Field               => ${(f.base or f).introspection_enum_literal}

      % if not f.abstract and not f.null:
         , Index => ${f.index + 1}
      % endif
   );
   % endfor

   Desc_For_${n.kwless_raw_name} : aliased constant Node_Type_Descriptor := (
      Is_Abstract       => ${n.abstract},
      Derivations_Count => ${len(n.subclasses)},
      Fields_Count      => ${len(fields)},
      Properties_Count  => ${len(properties)},

      Base_Type   => ${n.base.introspection_name if n.base else 'None'},
      Derivations =>
         ${('({})'.format(', '.join(
            '{} => {}'.format(i, child.introspection_name)
            for i, child in enumerate(n.subclasses, 1)
         )) if n.subclasses else '(1 .. 0 => <>)')},

      DSL_Name => To_Unbounded_String ("${n.dsl_name}"),

      Inherited_Fields => ${len(inherited_fields)},
      Fields           => (
         % if fields:
            ${', '.join("{} => {}_For_{}'Access"
                        .format(i, f.name, n.kwless_raw_name)
                        for i, f in enumerate(fields, 1))}
         % else:
            1 .. 0 => <>
         % endif
      ),

      Properties => (
         % if properties:
            ${', '.join("{} => {}".format(i, p.introspection_enum_literal)
                        for i, p in enumerate(properties, 1))}
         % else:
            1 .. 0 => <>
         % endif
      )

      % if not n.abstract:
      , Kind => ${n.ada_kind_name}
      % endif
   );
   % endfor

   Node_Type_Descriptors : constant
      array (Node_Type_Id) of Node_Type_Descriptor_Access
   := (${', '.join("Desc_For_{}'Access".format(n.kwless_raw_name)
                   for n in ctx.astnode_types)});

   ----------------------
   -- Various mappings --
   ----------------------

   package Node_Type_Id_Maps is new Ada.Containers.Hashed_Maps
     (Key_Type        => Unbounded_String,
      Element_Type    => Node_Type_Id,
      Equivalent_Keys => "=",
      Hash            => Hash);

   DSL_Name_To_Node_Type : Node_Type_Id_Maps.Map;
   --  Lookup table for DSL names to node type references. Created at
   --  elaboration time and never updated after.

   Kind_To_Id : constant array (${root_node_kind_name}) of Node_Type_Id := (
      ${', '.join('{n.ada_kind_name} => {n.introspection_name}'.format(n=n)
                  for n in ctx.astnode_types
                  if not n.abstract)}
   );

   ----------------
   -- Node types --
   ----------------

   function DSL_Name (Id : Node_Type_Id) return String;
   --  Implementation for Introspection.DSL_Name

   function Lookup_DSL_Name (Name : String) return Any_Node_Type_Id;
   --  Implementation for Introspection.Lookup_DSL_Name

   function Is_Abstract (Id : Node_Type_Id) return Boolean;
   --  Implementation for Introspection.Is_Abstract

   function Is_Concrete (Id : Node_Type_Id) return Boolean
   is (not Is_Abstract (Id));

   function Kind_For (Id : Node_Type_Id) return ${root_node_kind_name};
   --  Implementation for Introspection.Kind_For

   function Id_For_Kind (Kind : ${root_node_kind_name}) return Node_Type_Id;
   --  Implementation for Introspection.Id_For_Kind

   function Is_Root_Node (Id : Node_Type_Id) return Boolean;
   --  Implementation for Introspection.Is_Root_NOde

   function Base_Type (Id : Node_Type_Id) return Node_Type_Id;
   --  Implementation for Introspection.Base_Type

   function Derived_Types (Id : Node_Type_Id) return Node_Type_Id_Array;
   --  Implementation for Introspection.Derived_Types

   function Is_Derived_From (Id, Parent : Node_Type_Id) return Boolean;
   --  Implementation for Introspection.Is_Derived_From

   ---------------
   -- Node data --
   ---------------

   function Node_Data_Name (Node_Data : Node_Data_Reference) return String;
   --  Implementation for Introspection.Node_Data_Name

   function Node_Data_Type
     (Node_Data : Node_Data_Reference) return Value_Constraint;
   --  Implementation for Introspection.Node_Data_Type

   function Lookup_Node_Data
     (Id   : Node_Type_Id;
      Name : String) return Any_Node_Data_Reference;
   --  Implementation for Introspection.Lookup_Node_Data

   -------------------
   -- Syntax fields --
   -------------------

   function Field_Name (Field : Field_Reference) return String;
   --  Implementation for Introspection.Field_Name

   function Field_Type (Field : Field_Reference) return Node_Type_Id;
   --  Implementation for Introspection.Field_Type

   function Eval_Field
     (Node  : ${root_node_type_name};
      Field : Field_Reference) return ${root_node_type_name};
   --  Implementation for Introspection.Eval_Field

   function Index
     (Kind : ${root_node_kind_name}; Field : Field_Reference) return Positive;
   --  Implementation for Introspection.Index

   function Field_Reference_From_Index
     (Kind : ${root_node_kind_name}; Index : Positive) return Field_Reference;
   --  Implementation for Introspection.Field_Reference_From_Index

   function Fields
     (Id : Node_Type_Id; Concrete_Only : Boolean) return Field_Reference_Array;
   --  Return the list of fields associated to Id. If Concrete_Only is true,
   --  collect only non-null and concrete fields. Otherwise, collect all
   --  fields.

   function Fields
     (Kind : ${root_node_kind_name}) return Field_Reference_Array;
   --  Implementation for Introspection.Fields

   function Fields (Id : Node_Type_Id) return Field_Reference_Array;
   --  Implementation for Introspection.Fields

   % if ctx.sorted_properties:
   ----------------
   -- Properties --
   ----------------

   function Property_Name (Property : Property_Reference) return String;
   --  Implementation for Introspection.Property_Name

   function Property_Return_Type
     (Property : Property_Reference) return Value_Constraint;
   --  Implementation for Introspection.Property_Type

   function Property_Argument_Types
     (Property : Property_Reference) return Value_Constraint_Array;
   --  Implementation for Introspection.Property_Argument_Types

   function Property_Argument_Name
     (Property : Property_Reference; Argument_Number : Positive) return String;
   --  Implementation for Introspection.Property_Argument_Name

   function Property_Argument_Default_Value
     (Property        : Property_Reference;
      Argument_Number : Positive) return Internal_Value;
   --  Implementation for Introspection.Property_Argument_Default_Value

   function Properties
     (Kind : ${root_node_kind_name}) return Property_Reference_Array;
   --  Implementation for Introspection.Properties

   function Properties (Id : Node_Type_Id) return Property_Reference_Array;
   --  Implementation for Introspection.Properties

   procedure Check_Argument_Number
     (Desc : Property_Descriptor; Argument_Number : Positive);
   --  Raise a Property_Error if Argument_Number is not valid for the property
   --  that Desc describes. Do nothing otherwise.

   % endif

   ------------
   -- Tokens --
   ------------

   function Token_Node_Kind
     (Kind : ${root_node_kind_name}) return Token_Kind;
   --  Implementation for Introspection.Token_Node_Kind

end ${ada_lib_name}.Introspection_Implementation;
