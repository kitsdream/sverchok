
import bpy
from bpy.props import FloatProperty, EnumProperty, BoolProperty, IntProperty

from sverchok.node_tree import SverchCustomTreeNode
from sverchok.data_structure import updateNode, zip_long_repeat, ensure_nesting_level, get_data_nesting_level, repeat_last_for_length
from sverchok.utils.surface import SvSurface
from sverchok.utils.surface.nurbs import SvNurbsSurface

class SvSurfaceInsertKnotNode(bpy.types.Node, SverchCustomTreeNode):
    """
    Triggers: Insert Knot
    Tooltip: Insert a knot in a NURBS surface
    """
    bl_idname = 'SvSurfaceInsertKnotNode'
    bl_label = 'NURBS Surface - Insert Knot'
    bl_icon = 'OUTLINER_OB_EMPTY'
    sv_icon = 'SV_FLIP_CURVE'

    directions = [
            ('U', "U", "U direction", 0),
            ('V', "V", "V direction", 1)
        ]

    direction : EnumProperty(
            name = "Parameter",
            description = "From which parameter direction to remove the knot",
            items = directions,
            default = 'U',
            update = updateNode)

    knot : FloatProperty(
            name = "Knot",
            description = "New knot value",
            default = 0.5,
            update = updateNode)

    count : IntProperty(
            name = "Count",
            description = "Number of times to insert the knot",
            default = 1,
            min = 0,
            update = updateNode)
        
    def sv_init(self, context):
        self.inputs.new('SvSurfaceSocket', "Surface")
        self.inputs.new('SvStringsSocket', "Knot").prop_name = 'knot'
        self.inputs.new('SvStringsSocket', "Count").prop_name = 'count'
        self.outputs.new('SvSurfaceSocket', "Surface")

    def draw_buttons(self, context, layout):
        layout.prop(self, 'direction', expand=True)

    def process(self):
        if not any(socket.is_linked for socket in self.outputs):
            return

        surface_s = self.inputs['Surface'].sv_get()
        knot_s = self.inputs['Knot'].sv_get()
        count_s = self.inputs['Count'].sv_get()

        input_level = get_data_nesting_level(surface_s, data_types=(SvSurface,))
        flat_output = input_level < 2
        surface_s = ensure_nesting_level(surface_s, 2, data_types=(SvSurface,))
        knot_s = ensure_nesting_level(knot_s, 3)
        count_s = ensure_nesting_level(count_s, 3)

        surfaces_out = []
        for surfaces, knots_i, counts_i in zip_long_repeat(surface_s, knot_s, count_s):
            new_surfaces = []
            for surface, knots, counts in zip_long_repeat(surfaces, knots_i, counts_i):
                surface = SvNurbsSurface.get(surface)
                if surface is None:
                    raise Exception("One of surfaces is not NURBS")
                for knot, count in zip_long_repeat(knots, counts):
                    surface = surface.insert_knot(self.direction, knot, count)
                new_surfaces.append(surface)
            if flat_output:
                surfaces_out.extend(new_surfaces)
            else:
                surfaces_out.append(new_surfaces)

        self.outputs['Surface'].sv_set(surfaces_out)

def register():
    bpy.utils.register_class(SvSurfaceInsertKnotNode)

def unregister():
    bpy.utils.unregister_class(SvSurfaceInsertKnotNode)

