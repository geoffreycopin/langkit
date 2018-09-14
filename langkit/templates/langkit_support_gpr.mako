## vim: ft=makoada

with "gnatcoll";
with "gnatcoll_iconv";

library project Langkit_Support is

   type Build_Mode_Type is ("dev", "prod");
   Build_Mode : Build_Mode_Type := external ("BUILD_MODE", "dev");

   type Library_Kind_Type is ("static", "relocatable", "static-pic");
   Library_Kind_Param : Library_Kind_Type := external
     ("LIBRARY_TYPE", external ("LANGKIT_SUPPORT_LIBRARY_TYPE", "static"));

   for Languages use ("Ada", "C");
   for Library_Name use "langkit_support";
   for Library_Kind use Library_Kind_Param;
   for Interfaces use
     ("langkit_support.ads",
      "langkit_support-adalog.ads",
      "langkit_support-adalog-abstract_relation.ads",
      "langkit_support-adalog-abstract_relation.adb",
      "langkit_support-adalog-debug.ads",
      "langkit_support-adalog-debug.adb",
      "langkit_support-adalog-eq_same.ads",
      "langkit_support-adalog-eq_same.adb",
      "langkit_support-adalog-logic_ref.ads",
      "langkit_support-adalog-logic_ref.adb",
      "langkit_support-adalog-logic_var.ads",
      "langkit_support-adalog-main_support.ads",
      "langkit_support-adalog-main_support.adb",
      "langkit_support-adalog-operations.ads",
      "langkit_support-adalog-operations.adb",
      "langkit_support-adalog-predicates.ads",
      "langkit_support-adalog-predicates.adb",
      "langkit_support-adalog-pure_relations.ads",
      "langkit_support-adalog-pure_relations.adb",
      "langkit_support-adalog-relations.ads",
      "langkit_support-adalog-relations.adb",
      "langkit_support-adalog-unify.ads",
      "langkit_support-adalog-unify.adb",
      "langkit_support-adalog-unify_lr.ads",
      "langkit_support-adalog-unify_lr.adb",
      "langkit_support-adalog-unify_one_side.ads",
      "langkit_support-adalog-unify_one_side.adb",
      "langkit_support-array_utils.ads",
      "langkit_support-array_utils.adb",
      "langkit_support-boxes.ads",
      "langkit_support-boxes.adb",
      "langkit_support-bump_ptr.ads",
      "langkit_support-bump_ptr.adb",
      "langkit_support-bump_ptr-vectors.ads",
      "langkit_support-bump_ptr-vectors.adb",
      "langkit_support-cheap_sets.ads",
      "langkit_support-cheap_sets.adb",
      "langkit_support-diagnostics.ads",
      "langkit_support-diagnostics.adb",
      "langkit_support-extensions.adb",
      "langkit_support-extensions.ads",
      "langkit_support-hashes.ads",
      "langkit_support-hashes.adb",
      "langkit_support-images.ads",
      "langkit_support-images.adb",
      "langkit_support-iterators.ads",
      "langkit_support-iterators.adb",
      "langkit_support-lexical_env.ads",
      "langkit_support-lexical_env.adb",
      "langkit_support-packrat.ads",
      "langkit_support-packrat.adb",
      "langkit_support-relative_get.ads",
      "langkit_support-relative_get.adb",
      "langkit_support-slocs.ads",
      "langkit_support-slocs.adb",
      "langkit_support-symbols.ads",
      "langkit_support-symbols.adb",
      "langkit_support-text.ads",
      "langkit_support-text.adb",
      "langkit_support-token_data_handlers.ads",
      "langkit_support-token_data_handlers.adb",
      "langkit_support-types.ads",
      "langkit_support-tree_traversal_iterator.ads",
      "langkit_support-tree_traversal_iterator.adb",
      "langkit_support-vectors.ads",
      "langkit_support-vectors.adb");

   for Source_Dirs use (${string_repr(source_dir)});
   for Library_Dir use "../langkit_support." & Library_Kind_Param;
   for Object_Dir use "../../obj/langkit_support." & Library_Kind_Param;

   Common_Ada_Cargs := ("-gnatwa", "-gnatyg");
   Common_C_Cargs :=
     ("-I${quex_path}",
      "-DQUEX_OPTION_ASSERTS_DISABLED",
      "-DQUEX_OPTION_ASSERTS_WARNING_MESSAGE_DISABLED",
      "-DQUEX_OPTION_MULTI",
      "-D__QUEX_OPTION_PLAIN_C");

   package Compiler is
      case Build_Mode is
         when "dev" =>
            for Default_Switches ("Ada") use
               Common_Ada_Cargs & ("-g", "-O0", "-gnatwe", "-gnata");

            for Default_Switches ("C") use Common_C_Cargs & ("-g", "-O0");

         when "prod" =>
            --  Debug information is useful even with optimization for
            --  profiling, for instance.
            for Default_Switches ("Ada") use
               Common_Ada_Cargs & ("-g", "-Ofast", "-gnatp");

            for Default_Switches ("C") use Common_C_Cargs & ("-Ofast");
      end case;
   end Compiler;

end Langkit_Support;
