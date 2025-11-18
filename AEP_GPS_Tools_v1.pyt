# -*- coding: utf-8 -*-
"""
ArcGIS Python Toolbox for Uploading GPX Tracks
This script processes GPX files, buffers study areas, clips GPX data, and appends them to a Survey Tracks hosted feature layer.
Includes field validation, coded domain value mapping, logging, and error handling to ensure compatibility with the Survey Tracks layer schema.
"""

import os
import arcpy
import tempfile
import logging
from datetime import datetime


class Toolbox(object):
    def __init__(self):
        """Define the toolbox name and the tools contained."""
        self.label = "AEP_GPS_Tools_v1"
        self.alias = "aep_gps_tools_v1"

        # Add tools to the toolbox
        self.tools = [ImportGPXAndAppend]


class ImportGPXAndAppend(object):
    # Hard-coded endpoints
    STUDY_AREA_URL = "https://services-ap1.arcgis.com/1awYJ9qmpKeoPyqc/arcgis/rest/services/Project_Study_Area/FeatureServer/0"
    TARGET_FS_URL = "https://services-ap1.arcgis.com/1awYJ9qmpKeoPyqc/arcgis/rest/services/Survey_Track/FeatureServer/0"

    def __init__(self):
        """Define the tool's name, label, description, and other properties."""
        self.label = "Upload GPX Track to ArcGIS Online Tracks"
        self.description = (
            "This tool processes a GPX file, clips it to a buffered Study Area, "
            "and appends the resulting features to the Survey Tracks layer."
        )
        self.category = "GPX Files"
        self.canRunInBackground = False

        # Logging setup
        self.log_file = os.path.join(tempfile.gettempdir(), f"ImportGPXAndAppend_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        logging.basicConfig(filename=self.log_file, level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
        logging.info("Tool initialized successfully.")

    def getParameterInfo(self):
        """Define tool parameters."""
        logging.info("Defining parameters.")

        p0 = arcpy.Parameter(
            displayName="Input GPX Track File",
            name="in_gpx",
            datatype="DEFile",
            parameterType="Required",
            direction="Input"
        )
        p0.filter.list = ["gpx"]

        p1 = arcpy.Parameter(
            displayName="Project Number",
            name="project_number",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        project_numbers = self._get_project_numbers()
        if project_numbers:
            p1.filter.type = "ValueList"
            p1.filter.list = project_numbers
        else:
            arcpy.AddWarning("No project numbers found. Ensure the Study Area layer is accessible.")

        p2 = arcpy.Parameter(
            displayName="Surveyor (initials only)",
            name="surveyor",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )

        p3 = arcpy.Parameter(
            displayName="Survey Date",
            name="survey_date",
            datatype="GPDate",
            parameterType="Required",
            direction="Input"
        )

        p4 = arcpy.Parameter(
            displayName="Survey Type",
            name="survey_type",
            datatype="GPString",
            parameterType="Required",
            direction="Input"
        )
        survey_types = self._get_survey_type_domain()
        if survey_types:
            p4.filter.type = "ValueList"
            p4.filter.list = [desc for code, desc in survey_types.items()]

        p5 = arcpy.Parameter(
            displayName="Target Species",
            name="target_species",
            datatype="GPString",
            parameterType="Optional",
            direction="Input"
        )

        logging.info("Parameters defined successfully.")
        return [p0, p1, p2, p3, p4, p5]

    def _get_project_numbers(self):
        """Retrieve distinct project numbers from the Study Area layer."""
        logging.info("Fetching Project Numbers from the Study Area layer.")
        project_numbers = set()
        try:
            fields = [field.name for field in arcpy.ListFields(self.STUDY_AREA_URL)]
            if "project_number" not in fields:
                raise RuntimeError("'project_number' field is missing.")
            with arcpy.da.SearchCursor(self.STUDY_AREA_URL, ["project_number"]) as cursor:
                project_numbers = {row[0] for row in cursor if row[0]}
        except Exception as e:
            logging.error(f"Error retrieving project numbers: {e}")
        return sorted(project_numbers)

    def _get_survey_type_domain(self):
        """Retrieve Survey Type domain values."""
        logging.info("Retrieving Coded Value Domain for the Survey Type field.")
        domain_values = {}
        try:
            fields = arcpy.ListFields(self.TARGET_FS_URL)
            for field in fields:
                if field.name == "SurveyType" and field.domain:
                    domain_name = field.domain
                    workspace = arcpy.Describe(self.TARGET_FS_URL).path
                    for domain in arcpy.da.ListDomains(workspace):
                        if domain.name == domain_name:
                            domain_values = domain.codedValues
                            logging.info("Successfully retrieved Survey Type domain values.")
                            break
        except Exception as e:
            logging.error(f"Failed to fetch domain values: {e}")
        return domain_values

    def _ensure_fields(self, fc, required_fields):
        """Ensure that the required fields exist in the feature class."""
        logging.info(f"Ensuring required fields in {fc}.")
        existing_fields = {field.name for field in arcpy.ListFields(fc)}
        for field_name, field_type, length in required_fields:
            if field_name not in existing_fields:
                try:
                    if field_type == "TEXT":
                        arcpy.management.AddField(fc, field_name, field_type, field_length=length)
                    else:
                        arcpy.management.AddField(fc, field_name, field_type)
                    logging.info(f"Added missing field: {field_name} ({field_type}).")
                except Exception as e:
                    logging.error(f"Failed to add field '{field_name}': {e}")
                    arcpy.AddWarning(f"Could not add field '{field_name}'. Check permissions and schema.")

    def execute(self, parameters, messages):
        """Main execution logic."""
        logging.info("Tool execution started.")
        arcpy.AddMessage("Starting tool execution...")

        try:
            # Retrieve parameter values
            in_gpx = parameters[0].valueAsText
            project_number = parameters[1].valueAsText
            surveyor = parameters[2].valueAsText.strip().upper()
            survey_date = parameters[3].value
            survey_type_desc = parameters[4].valueAsText
            target_species = parameters[5].valueAsText if parameters[5].altered else None

            logging.info(f"Parameters - GPX: {in_gpx}, Project: {project_number}, Surveyor: {surveyor}, "
                         f"Survey Type: {survey_type_desc}, Target Species: {target_species}.")

            # Map survey type description to coded value
            survey_types = self._get_survey_type_domain()
            if survey_type_desc not in survey_types.values():
                raise ValueError(f"Invalid Survey Type: {survey_type_desc}. Unable to map to a coded value.")
            survey_type_code = [code for code, desc in survey_types.items() if desc == survey_type_desc][0]
            logging.info(f"Mapped Survey Type '{survey_type_desc}' to code '{survey_type_code}'.")

            # Convert GPX to line features
            line_fc = os.path.join(arcpy.env.scratchGDB, "gpx_tracks_line")
            arcpy.conversion.GPXtoFeatures(in_gpx, line_fc, "TRACKS_AS_LINES")
            line_count = int(arcpy.management.GetCount(line_fc).getOutput(0))
            if line_count == 0:
                raise RuntimeError("No features generated during GPX-to-line conversion.")
            logging.info(f"GPX conversion successful. Features generated: {line_count}")

            # Buffer and clip GPX data
            buffer_fc = os.path.join(arcpy.env.scratchGDB, "study_area_buffer")
            arcpy.analysis.Buffer(self.STUDY_AREA_URL, buffer_fc, "100 Meters")
            clip_fc = os.path.join(arcpy.env.scratchGDB, "clipped_gpx")
            arcpy.analysis.Clip(line_fc, buffer_fc, clip_fc)
            clip_count = int(arcpy.management.GetCount(clip_fc).getOutput(0))
            if clip_count == 0:
                raise RuntimeError("No overlapping features generated during clipping.")
            logging.info(f"GPX tracks clipped successfully: {clip_count} features.")

            # Ensure required fields are present in the clipped feature class
            required_fields = [
                ("Project_number", "TEXT", 10),
                ("StaffMember", "TEXT", 255),
                ("SurveyDate", "DATE", None),
                ("GPX_filename", "TEXT", 150),
                ("GPX_File_Path", "TEXT", 1000),
                ("Status", "TEXT", 15),
                ("SurveyType", "TEXT", 3),
                ("Target", "TEXT", 150)
            ]
            self._ensure_fields(clip_fc, required_fields)

            # Populate fields
            with arcpy.da.UpdateCursor(clip_fc, ["Project_number", "StaffMember", "SurveyDate",
                                                 "GPX_filename", "GPX_File_Path", "Status",
                                                 "SurveyType", "Target"]) as cursor:
                for row in cursor:
                    row[0] = project_number
                    row[1] = surveyor
                    row[2] = survey_date
                    row[3] = os.path.basename(in_gpx)[:150]
                    row[4] = in_gpx[:1000]
                    row[5] = "Raw"
                    row[6] = survey_type_code  # Use coded value (e.g., "TRA")
                    row[7] = target_species[:150] if target_species else None
                    cursor.updateRow(row)
            arcpy.AddMessage("Required fields populated successfully.")
            logging.info("Fields populated successfully.")

            # Append features to the target hosted layer
            arcpy.management.Append(clip_fc, self.TARGET_FS_URL, "NO_TEST")
            logging.info("GPX tracks successfully appended to Survey Tracks layer.")
            arcpy.AddMessage("GPX tracks successfully uploaded!")

        except arcpy.ExecuteError:
            logging.error(f"ArcPy error: {arcpy.GetMessages(2)}")
            arcpy.AddError(f"ArcPy error: {arcpy.GetMessages(2)}")
        except Exception as e:
            logging.error(f"Unexpected error occurred: {e}")
            arcpy.AddError(f"Unexpected error occurred: {e}")

