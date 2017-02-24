# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import bpy


class SvGenericCallbackWithParams(bpy.types.Operator):

    '''

    #### using SvGenericCallbackWithParams(bpy.types.Operator) #####

    class SomeNode..


        def draw_buttons(self, context, layout):
            callback = "node.sv_generic_callback_with_params"
            my_op = layout.operator(callback, text='display_name').fn_name='some_function'
            my_op.arg1 = 'something'


        def some_function(self, operator):
            print(operator.str1)
            operator.report({  ...})
            return {'FINISHED'}



    '''    

    bl_idname = "node.sv_generic_callback_with_params"
    bl_label = "SvGeneric callback (with params)"

    fn_name = bpy.props.StringProperty(default='')

    str1 = bpy.props.StringProperty()
    str2 = bpy.props.StringProperty()
    str3 = bpy.props.StringProperty()
    int1 = bpy.props.IntProperty()
    int2 = bpy.props.IntProperty()
    int3 = bpy.props.IntProperty()
    float1 = bpy.props.FloatProperty()
    float2 = bpy.props.FloatProperty()
    float3 = bpy.props.FloatProperty()


    def execute(self, context):
        try:
            f = getattr(context.node, self.fn_name)(self)
            return f or {'FINISHED'}

        except Exception as err:
            print(repr(err))
            return {'CANCELLED'}

        # return just in case, else let the content of the called function decide the return value
        return {'FINISHED'}



class SvGenericFileSelector(bpy.types.Operator):

    '''

    #### using SvGenericFileSelector(bpy.types.Operator) #####

    class SomeNode..

        def draw_buttons(self, context, layout):
            callback = "node.sv_generic_file_selector"
            my_op = layout.operator(callback, text='pick file').fn_name='some_function'


        def some_function(self, operator):
            print(operator.filepath)   <---- will contain full path to the file selected from the dialogue
            operator.report({  ...})
            return {'FINISHED'}


    '''    



    bl_idname = "node.sv_generic_file_selector"
    bl_label = "sv File Select"

    filepath = StringProperty(
        name="File Path",
        description="Filepath used for getting the file path",
        maxlen=1024, default="", subtype='FILE_PATH')

    def execute(self, context):
        try:
            f = getattr(context.node, self.fn_name)(self)
            return f or {'FINISHED'}

        except Exception as err:
            print(repr(err))
            return {'CANCELLED'}

        # return just in case, else let the content of the called function decide the return value
        return {'FINISHED'}


    def invoke(self, context, event):
        wm = context.window_manager
        wm.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SvGenericDirectorySelector(bpy.types.Operator):

    '''

    #### using SvGenericDirectorySelector(bpy.types.Operator) #####

    class SomeNode..

        def draw_buttons(self, context, layout):
            callback = "node.sv_generic_dir_selector"
            my_op = layout.operator(callback, text='pick directory').fn_name='some_function'


        def some_function(self, operator):
            print(operator.path)   <---- will contain full directory path selected from the dialogue
            operator.report({  ...})
            return {'FINISHED'}


    '''    



    bl_idname = "node.sv_generic_dir_selector"
    bl_label = "sv Dir Select"

    path = StringProperty(
        name="Base Path",
        description="Directory selected",
        maxlen=1024, default="", subtype='DIR_PATH')

    def execute(self, context):
        try:
            f = getattr(context.node, self.fn_name)(self)
            return f or {'FINISHED'}

        except Exception as err:
            print(repr(err))
            return {'CANCELLED'}

        # return just in case, else let the content of the called function decide the return value
        return {'FINISHED'}


    def invoke(self, context, event):
        wm = context.window_manager
        wm.fileselect_add(self)
        return {'RUNNING_MODAL'}




classese = [SvGenericCallbackWithParams, SvGenericFileSelector, SvGenericDirectorySelector ]

def register():
    for c in classes:
        bpy.utils.register_class(c)

def unregister():
    for c in classes:
        bpy.utils.unregister_class(c)
