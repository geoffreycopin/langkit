## vim: filetype=makoada

<%namespace name="scopes" file="scopes_ada.mako" />

<%
   codegen_element_var = map.element_vars[-1][0].name
   user_element_var = map.element_vars[0][0]

   array_var = map.result_var.name

   vec_var = map.result_var.name + Name('Vec')
   vec_pkg = map.type.pkg_vector
%>

${map.collection.render_pre()}

declare
   ${vec_var} : ${map.type.vector()};
begin

   <%def name="build_loop_body()">
      % if map.take_while:
      ${map.take_while.render_pre()}
      exit when not (${map.take_while.render_expr()});
      % endif

      ${map.expr.render_pre()}
      % if map.do_concat:
         <% expr = map.expr.render_expr() %>
         for Item_To_Append of
            % if map.expr.type.is_list_type:
               ${expr}.Nodes (1 .. ${expr}.Count)
            % else:
               ${expr}.Items
            % endif
         loop
            % if map.type.element_type.is_refcounted:
               Inc_Ref (Item_To_Append);
            % endif
            ${vec_pkg}.Append (${vec_var}, Item_To_Append);
         end loop;
      % else:
         declare
            Item_To_Append : constant ${map.type.element_type.name} :=
               ${map.expr.render_expr()};
         begin
            % if map.type.element_type.is_refcounted:
               Inc_Ref (Item_To_Append);
            % endif
            ${vec_pkg}.Append (${vec_var}, Item_To_Append);
         end;
      % endif
   </%def>

   <%def name="build_loop()">
      % if map.index_var:
         ${map.index_var.name} := 0;
      % endif

      ## First, build a vector for all the resulting elements
      <%
         coll_expr = map.collection.render_expr()
         if map.collection.type.is_list_type:
            coll_type = ctx.generic_list_type
            coll_expr = coll_type.internal_conversion(map.collection.type,
                                                      coll_expr)
         else:
            coll_type = map.collection.type
      %>
      declare
         Collection : constant ${coll_type.name} := ${coll_expr};
      begin
         for ${codegen_element_var} of
            % if map.collection.type.is_list_type:
               Collection.Nodes (1 .. Collection.Count)
            % else:
               Collection.Items
            % endif
         loop

            ## Initialize all element variables
            % for elt_var, init_expr in reversed(map.element_vars):
               % if init_expr:
                  ${init_expr.render_pre()}
                  ${assign_var(elt_var, init_expr.render_expr())}
               % endif
            % endfor

            ${scopes.start_scope(map.iter_scope)}

            ## Bind user iteration variables
            % if user_element_var.source_name:
               ${gdb_bind_var(user_element_var)}
            % endif
            % if map.index_var:
               ${gdb_bind_var(map.index_var)}
            % endif

            ## Emit the user body for the loop
            % if map.filter:
               ${map.filter.render_pre()}
               if ${map.filter.render_expr()} then
                  ${build_loop_body()}
               end if;
            % else:
               ${build_loop_body()}
            % endif

            % if map.index_var:
               ${map.index_var.name} := ${map.index_var.name} + 1;
            % endif
            ${scopes.finalize_scope(map.iter_scope)}
         end loop;
      end;

      ## Then convert the vector into the final array type
      ${array_var} := ${map.type.constructor_name}
        (Items_Count => Natural (${vec_pkg}.Length (${vec_var})));
      for I in ${array_var}.Items'Range loop
         ${array_var}.Items (I) := ${vec_pkg}.Get
           (${vec_var},
            I + ${vec_pkg}.Index_Type'First - ${array_var}.Items'First);
      end loop;
      ${vec_pkg}.Destroy (${vec_var});
   </%def>

   % if map.collection.type.is_list_type:
      ## Empty lists are null: handle this pecularity here to make it easier
      ## for property writers.

      if ${map.collection.render_expr()} = null then
         ${array_var} := ${map.type.constructor_name} (0);
      else
         ${build_loop()}
      end if;

   % else:
      ${build_loop()}
   % endif

end;
