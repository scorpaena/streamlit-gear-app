import tempfile
import os
from datetime import timedelta
from cadquery import Workplane, Edge, Wire, Vector, exporters
from math import radians, cos, tan, acos, degrees, sin
import pyvista as pv
from stpyvista import stpyvista as stv
import streamlit as st


# ----------------------- Gear Geometry Calculation ----------------------- #

class GearGeometry:
    """Class to handle the generation of gear geometry."""

    def __init__(self, module, teeth, pressure_angle=20, shift=0, points_per_curve=20):
        self.module = module
        self.teeth = teeth
        self.pressure_angle = radians(pressure_angle)
        self.shift = shift
        self.points_per_curve = points_per_curve

        # Calculated radii
        self.ref_radius = self.module * self.teeth / 2
        self.base_radius = self.ref_radius * cos(self.pressure_angle)
        self.top_radius = self.ref_radius + self.module * (1 + self.shift)
        self.dedendum_radius = self.ref_radius - 1.25 * self.module

    def involute_curve(self, sign=1):
        """Returns a function for generating involute curve points."""

        def curve_function(radius):
            alpha = sign * acos(self.base_radius / radius)
            x = radius * cos(tan(alpha) - alpha)
            y = radius * sin(tan(alpha) - alpha)
            return x, y

        return curve_function

    def create_tooth_profile(self):
        """Creates a single tooth profile."""
        # Angle calculations
        angle_inv = tan(self.pressure_angle) - self.pressure_angle
        angle_tip_inv = tan(acos(self.base_radius / self.top_radius)) - acos(self.base_radius / self.top_radius)
        a = 90 / self.teeth + degrees(angle_inv)
        a2 = 90 / self.teeth + degrees(angle_inv) - degrees(angle_tip_inv)
        a3 = 360 / self.teeth - a

        # Define tooth edges
        right_edge = (
            Workplane()
            .transformed(rotate=(0, 0, a))
            .parametricCurve(self.involute_curve(sign=-1), start=self.base_radius, stop=self.top_radius,
                             N=self.points_per_curve, makeWire=False)
            .val()
        )

        left_edge = (
            Workplane()
            .transformed(rotate=(0, 0, -a))
            .parametricCurve(self.involute_curve(sign=1), start=self.base_radius, stop=self.top_radius,
                             N=self.points_per_curve, makeWire=False)
            .val()
        )

        # Define other edges
        top_edge = Edge.makeCircle(self.top_radius, angle1=-a2, angle2=a2)
        bottom_edge = Edge.makeCircle(self.dedendum_radius, angle1=-a3, angle2=-a)
        side_edge = Edge.makeLine(Vector(self.dedendum_radius, 0), Vector(self.base_radius, 0))
        side1 = side_edge.rotate(Vector(0, 0, 0), Vector(0, 0, 1), -a)
        side2 = side_edge.rotate(Vector(0, 0, 0), Vector(0, 0, 1), -a3)

        # Assemble and return tooth profile
        tooth_profile = Wire.assembleEdges([left_edge, top_edge, right_edge, side1, bottom_edge, side2])
        return tooth_profile

    def create_gear_profile(self):
        """Creates the complete gear profile."""
        tooth_profile = self.create_tooth_profile()
        gear_profile = (
            Workplane()
            .polarArray(0, 0, 360, self.teeth)
            .each(lambda loc: tooth_profile.located(loc))
            .consolidateWires()
        )
        return gear_profile.val()


# ----------------------- Gear Model Generation ----------------------- #

def generate_gear(module, teeth, center_hole_dia, height):
    """Generates the complete gear model with specified parameters."""
    gear_geom = GearGeometry(module, teeth)
    gear_profile = gear_geom.create_gear_profile()

    # Create gear by duplicating tooth profile
    gear_blank = Workplane(obj=gear_profile).toPending().extrude(height)

    # Cut center hole
    gear_with_hole = gear_blank.faces(">Z").workplane().circle(center_hole_dia / 2).cutThruAll()

    key_slot = (
        Workplane("XY")
        .rect(center_hole_dia * 0.25, center_hole_dia * 0.25, centered=(True, True))  # Create a rectangular key slot profile
        .extrude(height)  # Extrude the slot through the gear height
        .translate((0, center_hole_dia / 2, 0))  # Position the slot on the edge of the center hole
    )

    return gear_with_hole.cut(key_slot)


def generate_temp_file(model, file_format):
    """Generates a temporary file with the specified STL or STEP format."""
    if file_format.lower() == "stl":
        file_suffix = ".stl"
        export_type = exporters.ExportTypes.STL

    elif file_format.lower() == "step":
        file_suffix = ".step"
        export_type = exporters.ExportTypes.STEP
    else:
        raise ValueError(f"Unsupported file format: {file_format}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_suffix) as tmpfile:
        exporters.export(model, tmpfile.name, exportType=export_type)
        return tmpfile.name

# ----------------------- Streamlit UI ----------------------- #

# Streamlit UI for parameter inputs
st.set_page_config(layout='wide')
col1, col2, col3 = st.columns([3, 0.5, 4])
with col1:
    st.subheader("Gear Model Generator")
    module = st.slider('Module (m)', min_value=1, max_value=5, value=1, step=1)
    teeth = st.slider('Number of teeth (z)', min_value=17, max_value=30, value=20, step=1)
    height = st.slider('Gear height (h)', min_value=10, max_value=30, value=20, step=5)
    center_hole_dia = st.slider('Center hole diameter (d)', min_value=5, max_value=12, value=5, step=1)


# Caching and exporting gear model
@st.cache_data(ttl=timedelta(seconds=int(os.getenv("CACHE_LIFE_PERIOD"))), max_entries=100)
def generate_and_export_gear_cached(module, teeth, center_hole_dia, height, file_format):
    gear = generate_gear(module, teeth, center_hole_dia, height)
    return generate_temp_file(gear, file_format)

# ----------------------- Visualization ----------------------- #

file_path_stl = generate_and_export_gear_cached(module, teeth, center_hole_dia, height, "stl")

if os.getenv("OS_TYPE") != "windows":
    pv.start_xvfb()

mesh = pv.read(file_path_stl)

plotter = pv.Plotter(window_size=[500, 500])
plotter.add_mesh(mesh)
plotter.view_isometric()
plotter.set_background("#0e1117")

with col3:
    stv(plotter, key=f"gear_{module}_{teeth}_{center_hole_dia}_{height}")
    with open(file_path_stl, 'rb') as stl_file:
        st.download_button(
            label="Download STL File",
            data=stl_file,
            file_name="gear.stl",
            mime="application/vnd.ms-pki.stl",
        )
    with open(generate_and_export_gear_cached(module, teeth, center_hole_dia, height, "step"), 'rb') as step_file:
        st.download_button(
            label=f"Download STEP File",
            data=step_file,
            file_name=f"gear.step",
            mime="application/step",
        )
