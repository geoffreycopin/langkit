## vim: filetype=makoada

with ${ada_lib_name}.Implementation;
use ${ada_lib_name}.Implementation;

with ${ada_lib_name}.Converters; use ${ada_lib_name}.Converters;
with ${ada_lib_name}.Unparsing_Implementation;
use ${ada_lib_name}.Unparsing_Implementation;

package body ${ada_lib_name}.Unparsing is

   -------------
   -- Unparse --
   -------------

   function Unparse (Node : ${root_entity.api_name}'Class) return String is
      N : constant ${root_node_type_name} := Unwrap_Node (Node);
   begin
      return Unparse
        (Create_Abstract_Node (N),
         Unwrap_Node (Node).Unit,
         Preserve_Formatting => False,
         As_Unit             => False);
   end Unparse;

end ${ada_lib_name}.Unparsing;
