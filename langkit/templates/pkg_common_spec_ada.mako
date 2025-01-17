## vim: filetype=makoada

<%namespace name="exts" file="extensions.mako" />

with Langkit_Support.Slocs;   use Langkit_Support.Slocs;
with Langkit_Support.Symbols;
with Langkit_Support.Text;    use Langkit_Support.Text;
with Langkit_Support.Token_Data_Handlers;

with GNATCOLL.GMP.Integers;
with GNATCOLL.Traces;

--  This package provides types and functions used in the whole ${ada_lib_name}
--  package tree.

package ${ada_lib_name}.Common is

   <%
      lexer = ctx.lexer
      tokens = lexer.sorted_tokens
   %>

   Main_Trace : constant GNATCOLL.Traces.Trace_Handle :=
     GNATCOLL.Traces.Create
       ("${ctx.lib_name.upper}.MAIN_TRACE", GNATCOLL.Traces.From_Config);

   Default_Charset : constant String := ${string_repr(ctx.default_charset)};
   --  Default charset to use when creating analysis contexts

   subtype Big_Integer is GNATCOLL.GMP.Integers.Big_Integer;
   --  Shortcut for ``GNATCOLL.GMP.Integers.Big_Integer``

   -------------------------------------
   -- Symbols and token data handlers --
   -------------------------------------

   type Precomputed_Symbol_Index is
      % if ctx.symbol_literals:
         (
            <%
               sym_items = ctx.sorted_symbol_literals
               last_i = len(sym_items) - 1
            %>
            % for i, (sym, name) in enumerate(sym_items):
               ${name}${',' if i < last_i else ''} --  ${sym}
            % endfor
         )
      % else:
         new Integer range 1 .. 0
      % endif
   ;

   function Precomputed_Symbol
     (Index : Precomputed_Symbol_Index) return Text_Type;

   package Symbols is new Langkit_Support.Symbols
     (Precomputed_Symbol_Index, Precomputed_Symbol);

   package Token_Data_Handlers is new Langkit_Support.Token_Data_Handlers
     (Precomputed_Symbol_Index, Precomputed_Symbol, Symbols);

   use Symbols, Token_Data_Handlers;

   -----------
   -- Nodes --
   -----------

   ## Output enumerators so that all concrete AST_Node subclasses get their own
   ## kind. Nothing can be an instance of an abstract subclass, so these do not
   ## need their own kind.
   type ${root_node_kind_name} is
     (${', '.join(cls.ada_kind_name
                  for cls in ctx.astnode_types
                  if not cls.abstract)});
   --  Type for concrete nodes

   for ${root_node_kind_name} use
     (${', '.join('{} => {}'.format(cls.ada_kind_name,
                                    ctx.node_kind_constants[cls])
                  for cls in ctx.astnode_types
                  if not cls.abstract)});

   ## Output subranges to materialize abstract classes as sets of their
   ## concrete subclasses.
   % for cls in ctx.astnode_types:
      % if cls.concrete_subclasses:
         subtype ${cls.ada_kind_range_name} is
            ${root_node_kind_name} range
               ${'{} .. {}'.format(*cls.ada_kind_range_bounds)};
         --% no-document: True
      % endif
   % endfor

   ## Output a subtype to materialize the set of kinds for synthetic nodes
   subtype Synthetic_Nodes is ${root_node_kind_name}
      with Static_Predicate =>
      % if ctx.synthetic_nodes:
         Synthetic_Nodes in
         ${' | '.join(cls.ada_kind_name for cls in ctx.synthetic_nodes)}
      % else:
         False
      % endif
   ;
   ${ada_doc('langkit.synthetic_nodes', 6)}

   % for enum_type in ctx.enum_types:
      type ${enum_type.api_name} is
        (${', '.join(str(v.name) for v in enum_type.values)})
         with Convention => C;
      ${ada_doc(enum_type, 6)}
   % endfor

   Default_Grammar_Rule : constant Grammar_Rule := ${ctx.main_rule_api_name};
   --  Default grammar rule to use when parsing analysis units

   type Lexer_Input_Kind is
     (File,
      --  Readable source file

      Bytes_Buffer,
      --  Buffer of undecoded bytes

      Text_Buffer
      --  Buffer of decoded bytes
   );
   --  Kind of lexer input

   type Token_Kind is (
      ${',\n'.join(t.ada_name for t in tokens)}
   );
   --  Kind of token: indentifier, string literal, ...

   type Token_Family is
     (${', '.join(tf.ada_name for tf in lexer.tokens.token_families)});
   --  Groups of token kinds, to make the processing of some groups of token
   --  uniform.

   % if lexer.track_indent:
   type Indent_Kind is (Indent, Dedent, Nodent, None);
   --  Change of indentation
   % endif

   Token_Kind_To_Family : array (Token_Kind) of Token_Family :=
     (${', '.join('{} => {}'.format(t.ada_name,
                                     lexer.tokens.token_to_family[t].ada_name)
                   for t in tokens)});
   --  Associate a token family to all token kinds
   --
   --% document-value: False

   function Token_Kind_Name (Token_Id : Token_Kind) return String;
   ${ada_doc('langkit.token_kind_name', 3)}

   function Token_Kind_Literal (Token_Id : Token_Kind) return Text_Type;
   --  Return the canonical literal corresponding to this token kind, or an
   --  empty string if this token has no literal.

   function Token_Error_Image (Token_Id : Token_Kind) return String;
   --  Return a string representation of ``Token_Id`` that is suitable in error
   --  messages.

   function Is_Token_Node (Kind : ${root_node_kind_name}) return Boolean;
   --  Return whether Kind corresponds to a token node

   function Is_List_Node (Kind : ${root_node_kind_name}) return Boolean;
   --  Return whether Kind corresponds to a list node

   type Visit_Status is (Into, Over, Stop);
   --  Helper type to control the node traversal process. See the
   --  ``${ada_lib_name}.Analysis.Traverse`` function.

   -----------------------
   -- Lexical utilities --
   -----------------------

   type Token_Reference is private;
   ${ada_doc('langkit.token_reference_type', 3)}

   No_Token : constant Token_Reference;

   type Token_Data_Type is private;

   function "<" (Left, Right : Token_Reference) return Boolean;
   --  Assuming ``Left`` and ``Right`` belong to the same analysis unit, return
   --  whether ``Left`` came before ``Right`` in the source file.

   function Next
     (Token          : Token_Reference;
      Exclude_Trivia : Boolean := False) return Token_Reference;
   ${ada_doc('langkit.token_next', 3)}

   function Previous
     (Token          : Token_Reference;
      Exclude_Trivia : Boolean := False) return Token_Reference;
   ${ada_doc('langkit.token_previous', 3)}

   function Data (Token : Token_Reference) return Token_Data_Type;
   --  Return the data associated to ``Token``

   function Is_Equivalent (L, R : Token_Reference) return Boolean;
   ${ada_doc('langkit.token_is_equivalent', 3)}

   function Image (Token : Token_Reference) return String;
   --  Debug helper: return a human-readable text to represent a token

   function Text (Token : Token_Reference) return Text_Type;
   --  Return the text of the token as ``Text_Type``

   function Debug_Text (Token : Token_Reference) return String;
   --  Return the text of the token as ``String``

   function Text (First, Last : Token_Reference) return Text_Type;
   ${ada_doc('langkit.token_range_text', 3)}

   function Debug_Text (First, Last : Token_Reference) return String;
   --  Like ``Text``, to get the source buffer slice as a string

   function Get_Symbol (Token : Token_Reference) return Symbol_Type;
   --  Assuming that ``Token`` refers to a token that contains a symbol, return
   --  the corresponding symbol.

   function Kind (Token_Data : Token_Data_Type) return Token_Kind;
   ${ada_doc('langkit.token_kind', 3)}

   function Is_Trivia (Token : Token_Reference) return Boolean;
   ${ada_doc('langkit.token_is_trivia', 3)}

   function Is_Trivia (Token_Data : Token_Data_Type) return Boolean;
   ${ada_doc('langkit.token_is_trivia', 3)}

   function Index (Token : Token_Reference) return Token_Index;
   ${ada_doc('langkit.token_index', 3)}

   function Index (Token_Data : Token_Data_Type) return Token_Index;
   ${ada_doc('langkit.token_index', 3)}

   function Sloc_Range
     (Token_Data : Token_Data_Type) return Source_Location_Range;
   --  Source location range for this token. Note that the end bound is
   --  exclusive.

   function Convert
     (TDH      : Token_Data_Handler;
      Token    : Token_Reference;
      Raw_Data : Stored_Token_Data) return Token_Data_Type;
   --  Turn data from ``TDH`` and ``Raw_Data`` into a user-ready token data
   --  record.

   type Child_Or_Trivia is (Child, Trivia);
   --  Discriminator for the ``Child_Record`` type

   type Symbolization_Result (Success : Boolean; Size : Natural) is record
      case Success is
         when True  =>
            Symbol : Text_Type (1 .. Size);
            --  Text for successfully symbolized identifiers

         when False =>
            Error_Message : Text_Type (1 .. Size);
            --  Message describing why symbolization failed
      end case;
   end record;
   --  Holder for results of the symbolization process, conditionned by whether
   --  this process was successful.

   function Create_Symbol (Name : Text_Type) return Symbolization_Result is
     ((Success => True, Size => Name'Length, Symbol => Name));
   --  Shortcut to create successful symbolization results

   function Create_Error (Message : Text_Type) return Symbolization_Result is
     ((Success => False, Size => Message'Length, Error_Message => Message));
   --  Shortcut to create failed symbolization results

   function Raw_Data (T : Token_Reference) return Stored_Token_Data;
   --  Return the raw token data for ``T``

   procedure Raise_Property_Error (Message : String := "");
   --  Raise a ``Property_Error`` with the given message

   ## Emit declarations for all exceptions
   % for section_name, exceptions in ctx.exceptions_by_section:
   % if section_name:
   ${comment_box(section_name, 3)}

   % endif
   % for doc_name, exc_name in exceptions:
   ${exc_name} : exception;
   ${ada_doc(doc_name, 3)}

   % endfor
   % endfor

   -------------------
   -- Introspection --
   -------------------

   --  Unlike ${root_node_kind_name}, the following enumeration contains
   --  entries for abstract nodes.

   type Any_Node_Type_Id is (
      None, ${', '.join(n.introspection_simple_name
                        for n in ctx.astnode_types)}
   );

   subtype Node_Type_Id is Any_Node_Type_Id
      range ${ctx.astnode_types[0].introspection_simple_name}
            .. ${ctx.astnode_types[-1].introspection_simple_name};

   type Node_Type_Id_Array is array (Positive range <>) of Node_Type_Id;

   type Any_Value_Kind is (
      None,
      Boolean_Value,
      Integer_Value,
      Big_Integer_Value,
      Character_Value,
      Token_Value,
      Unbounded_Text_Value,
      Analysis_Unit_Value,
      Node_Value

      % for enum_type in ctx.enum_types:
      , ${enum_type.introspection_kind}
      % endfor

      % for t in ctx.composite_types:
      % if t.exposed and not t.is_entity_type:
      , ${t.introspection_kind}
      % endif
      % endfor
   );
   subtype Value_Kind is
      Any_Value_Kind range Boolean_Value ..  Any_Value_Kind'Last;
   --  Enumeration for all types used to interact with properties

   type Value_Constraint (Kind : Value_Kind := Value_Kind'First) is record
      case Kind is
         when Node_Value =>
            Node_Type : Node_Type_Id;
            --  Base type for nodes that satisfy this constraint

         when others =>
            null;
      end case;
   end record;
   --  Constraint for a polymorphic value

   type Value_Constraint_Array is
      array (Positive range <>) of Value_Constraint;

   <% all_abstract = ctx.sorted_parse_fields + ctx.sorted_properties %>

   type Any_Node_Data_Reference is
      (None${''.join((', ' + f.introspection_enum_literal)
                      for f in all_abstract)});
   subtype Node_Data_Reference is Any_Node_Data_Reference range
      ${all_abstract[0].introspection_enum_literal}
      ..  ${all_abstract[-1].introspection_enum_literal};
   --  Enumeration of all data attached to nodes (syntax fields and properties)

   type Node_Data_Reference_Array is
      array (Positive range <>) of Node_Data_Reference;

   ## In a lot of testcases, there is a single concrete node that has no
   ## field. For these, generate a type that has no valid value.
   subtype Field_Reference is Node_Data_Reference range
      % if ctx.sorted_parse_fields:
         <%
            first = ctx.sorted_parse_fields[0]
            last = ctx.sorted_parse_fields[-1]
         %>
      % else:
         <%
            first = all_abstract[-1]
            last = all_abstract[0]
         %>
      % endif
      ${first.introspection_enum_literal}
      .. ${last.introspection_enum_literal}
   ;
   --  Enumeration of all syntax fields for regular nodes

   type Field_Reference_Array is array (Positive range <>) of Field_Reference;

   subtype Property_Reference is Node_Data_Reference
      range ${ctx.sorted_properties[0].introspection_enum_literal}
         .. ${ctx.sorted_properties[-1].introspection_enum_literal};
   --  Enumeration of all available node properties

   type Property_Reference_Array is
      array (Positive range <>) of Property_Reference;

   ${exts.include_extension(ctx.ext('common', 'public_decls'))}

private

   type Token_Reference is record
      TDH : Token_Data_Handler_Access;
      --  Token data handler that owns this token

      Index : Token_Or_Trivia_Index;
      --  Identifier for the trivia or the token this refers to
   end record;

   No_Token : constant Token_Reference := (null, No_Token_Or_Trivia_Index);

   type Token_Data_Type is record
      Kind : Token_Kind;
      --  See documentation for the Kind accessor

      Is_Trivia : Boolean;
      --  See documentation for the Is_Trivia accessor

      Index : Token_Index;
      --  See documentation for the Index accessor

      Source_Buffer : Text_Cst_Access;
      --  Text for the original source file

      Source_First : Positive;
      Source_Last  : Natural;
      --  Bounds in Source_Buffer for the text corresponding to this token

      Sloc_Range : Source_Location_Range;
      --  See documenation for the Sloc_Range accessor
   end record;

end ${ada_lib_name}.Common;
