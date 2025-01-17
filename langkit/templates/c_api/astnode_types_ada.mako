## vim: filetype=makoada

<%def name="accessor_profile(field)">
   <%
      accessor_name = capi.get_name(field.accessor_basename)
      entity_type = root_entity.c_type(capi).name
   %>

   function ${accessor_name}
     (Node : ${entity_type}_Ptr;

      % for arg in field.arguments:
         ${arg.name} :
            ${'access constant' if arg.public_type.is_ada_record else ''}
            ${arg.public_type.c_type(capi).name};
      % endfor

      Value_P : access ${field.public_type.c_type(capi).name}) return int
</%def>

<%def name="accessor_decl(field)">
   <% accessor_name = capi.get_name(field.accessor_basename) %>

   ${accessor_profile(field)}
      with Export        => True,
           Convention    => C,
           External_name => "${accessor_name}";
   ${ada_doc(field, 3, lang='c')}
</%def>


<%def name="accessor_body(field)">

   <%
      struct = field.struct
      accessor_name = capi.get_name(field.accessor_basename)

      def simple_wrapping(t):
         return (t.is_lexical_env_type
                 or t.is_equation_type
                 or t.is_logic_var_type
                 or t.is_env_rebindings_type)
   %>

   ${accessor_profile(field)}
   is
      Unwrapped_Node : constant ${root_node_type_name} := Node.Node;
      ## For each input argument, convert the C-level value into an Ada-level
      ## one.
      % for arg in field.arguments:
         <%
            arg_ref = arg.name

            if arg.type.is_ada_record:
               arg_ref = '{}.all'.format(arg_ref)
         %>
         Unwrapped_${arg.name} : constant ${arg.type.name} :=
            % if arg.type.is_bool_type:
               ${arg_ref} /= 0
            % elif arg.type.is_long_type:
               Integer (${arg_ref})
            % elif arg.type.is_character_type:
               Character_Type'Val (${arg_ref})
            % elif arg.type.is_analysis_unit_type:
               ${arg_ref}
            % elif arg.type.is_ast_node:
               ${arg.type.internal_conversion(
                    T.root_node, '{}.Node'.format(arg_ref))}
            % elif arg.type.is_entity_type:
               (if ${arg_ref}.Node = null
                then ${arg.type.nullexpr}
                else (${arg.type.element_type.internal_conversion(
                           T.root_node, '{}.Node'.format(arg_ref))},
                      ${arg_ref}.Info))
            % elif arg.type.is_array and not arg.type.emit_c_type:
               Convert (${arg_ref})
            % elif arg.type.is_token_type:
               Unwrap (${arg_ref})
            % elif arg.type.is_symbol_type:
               Unwrap_Symbol (${arg_ref})
            % elif arg.type.is_big_integer_type:
               Unwrap_Big_Integer (${arg_ref})
            % elif simple_wrapping(arg.type):
               Unwrap (${arg_ref})
            % else:
               ${arg_ref}
            % endif
         ;
      % endfor
   begin
      Clear_Last_Exception;

      % for arg in field.arguments:
         % if arg.type.is_token_type:
            if Converters.Get_Token_TDH.all (Unwrapped_${arg.name})
               /= Unwrapped_Node.Unit.TDH'Access
            then
               raise Constraint_Error with
                 ("The input token does not belong to the same unit as"
                  & " the input node");
            end if;
         % endif
      % endfor

      % if not struct.equivalent_to_root:
      if Unwrapped_Node.Kind in ${struct.ada_kind_range_name} then
      % endif

         declare
            <%
              actuals = ['Typed_Node'] + [
                 '{0.name} => Unwrapped_{0.name}'.format(a)
                 for a in field.arguments]
              if field.is_property and field.uses_entity_info:
                  actuals.append('{} => Node.Info'.format(
                      field.entity_info_name
                  ))
              field_access = '{} ({})'.format(field.name, ', '.join(actuals))
            %>

            Typed_Node : constant ${struct.name} :=
               ${struct.internal_conversion(T.root_node, 'Unwrapped_Node')};
            Result     : ${field.type.name};
         begin
            ##  Keep this assignment after the BEGIN keyword above so that the
            ##  exception handler covers it.
            Result := ${field_access};

            Value_P.all :=
               % if field.type.is_bool_type:
                   ${bool_type} (Boolean'Pos (Result))
               % elif field.type.is_long_type:
                   int (Result)
               % elif field.type.is_character_type:
                   Character_Type'Pos (Result)
               % elif field.type.is_analysis_unit_type:
                   Result
               % elif field.type.is_ast_node:
                   (${T.root_node.internal_conversion(field.type, 'Result')},
                    Node.Info)
               % elif field.type.is_entity_type:
                  (${T.root_node.internal_conversion(
                        field.type, 'Result.Node')},
                   Result.Info)
               % elif field.type.is_array and not field.type.emit_c_type:
                  Convert (Result)
               % elif field.type.is_token_type:
                   Wrap (Result)
               % elif field.type.is_symbol_type:
                   Wrap_Symbol (Result)
               % elif field.type.is_big_integer_type:
                   Wrap_Big_Integer (Result)
               % elif simple_wrapping(field.type):
                   Wrap (Result)
               % else:
                   Result
               % endif
            ;

            return 1;
         exception
            when Exc : Property_Error =>
               ## If we reach this handler, it means the expression failed at
               ## some point because of a safety check. Tell the user about
               ## it.
               Set_Last_Exception (Exc);
               return 0;
         end;

      % if not struct.equivalent_to_root:
      else
         return 0;
      end if;
      % endif

   exception
      when Exc : others =>
         Set_Last_Exception (Exc);
         return 0;
   end ${accessor_name};

</%def>
