#
# Copyright (c) 2020-2021 Massachusetts General Hospital. All rights reserved. 
# This program and the accompanying materials  are made available under the terms 
# of the Mozilla Public License v. 2.0 ( http://mozilla.org/MPL/2.0/) and under 
# the terms of the Healthcare Disclaimer.
#

import os
from pathlib import Path
import csv
from datetime import datetime as DateTime
from Mozilla.exception.mozilla_cdi_max_err_reached import MaxErrorCountReachedError
from i2b2_cdi.log import logger
from alive_progress import alive_bar
from i2b2_cdi.common.utils import *
from i2b2_cdi.patient import patient_mapping as PatientMapping
from i2b2_cdi.encounter import encounter_mapping as EncounterMapping
from i2b2_cdi.common import constants as constant
from i2b2_cdi.encounter.deid_encounter import *

class MozillaDeidEncounter:
    """The class provides the interface for de-identifying i.e. (mapping src encounter id to i2b2 generated encounter num) encounter file"""

    def __init__(self,max_validation_error_count):
        self.date_format = ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d/%m/%y', '%d/%m/%y %H:%M', '%d/%m/%y %H:%M:%S')
        self.err_records_max = int(max_validation_error_count)
        self.write_batch_size = 100
        now = DateTime.now()
        self.import_time = now.strftime("%Y-%m-%d %H:%M:%S")
        self.deid_header = ['encounterid', 'mrn', 'startdate',
                            'enddate', 'activitytypecd', 'activitystatuscd', 'programcd']
        self.error_file_header = []
        self.error_headers = ['ValidationError', 'ErrorRowNumber']

    def deidentify_encounter(self, config, patient_map, encounter_map, csv_file_path, deid_file_path, error_file_path):
        """This method de-identifies csv file and error records will be logged to log file

        Args:
            patient_map (:obj:`str`, mandatory): Patient map for de-identification.
            encounter_map (:obj:`str`, mandatory): Encounter map for de-identification.
            csv_file_path (:obj:`str`, mandatory): Path to the input csv file which needs to be de-identified
            input_csv_delimiter (:obj:`str`, mandatory): Delimiter of the input csv file, which will be used while reading csv file.
            deid_file_path (:obj:`str`, mandatory): Path to the de-identified output file.
            output_deid_delimiter (:obj:`str`, mandatory): Delimiter of the output deid file, which will be used while writing deid file.
            error_file_path (:obj:`str`, mandatory): Path to the error file, which contains error records

        """
        _error_rows_arr = []
        _valid_rows_arr = []
        max_line = file_len(csv_file_path)
        logger.debug('De-identifing encounter file : {}', csv_file_path)
        try:
            # Read input csv file
            with open(csv_file_path, mode='r', encoding='utf-8-sig') as csv_file:
                csv_reader = csv.DictReader(
                    csv_file, delimiter=config.csv_delimiter)
                csv_reader.fieldnames = [c.replace('-','').replace('_','').replace(' ','').lower() for c in csv_reader.fieldnames]
                self.error_file_header = csv_reader.fieldnames + self.error_headers
                write_deid_file_header(self.deid_header,deid_file_path, config.csv_delimiter)
                write_error_file_header(self.error_file_header,error_file_path)
                print('\n')

                row_number = 0
                with alive_bar(max_line, bar='smooth') as bar:
                    for row in csv_reader:
                        _validation_error = []
                        row_number += 1

                        # Check if parsing error in row
                        if None in row.keys():
                            row['ValidationError'] = 'Row Parsing Error'
                            row['ErrorRowNumber'] = str(row_number)
                            _error_rows_arr.append(row)
                            del row[None]
                            continue
                        # Validate encounterid 
                        if 'encounterid' in csv_reader.fieldnames:
                            if not row['encounterid']:
                                _validation_error.append("Encounter ID is Null")
                            elif is_length_exceeded(row['encounterid'], 200):
                                _validation_error.append(constant.FIELD_LENGTH_VALIDATION_MSG.format(
                                    field="EncounterID", length=200))
                            # Replace src encounter id by i2b2 encounter num
                            encounter_num = encounter_map.get(row['encounterid'])
                            if encounter_num is None:
                                _validation_error.append(
                                    "Encounter mapping not found")
                            else:
                                row['encounterid'] = encounter_num
                        else:
                            logger.error("Mandatory column, 'encounterid' does not exists in csv file")
                            raise Exception("Mandatory column, 'encounterid' does not exists in csv file")
                        
                        _validation_error = validatations(_validation_error, csv_reader, patient_map, row)

                        # Validate start date
                        if 'startdate' in csv_reader.fieldnames:
                            if row['startdate']:
                                parsed_date = parse_date(row['startdate'])
                                if parsed_date is None:
                                    _validation_error.append("Invalid start date format")
                                else:
                                    row['startdate'] = parsed_date
                        # Validate end date
                        if 'enddate' in csv_reader.fieldnames:
                            if row['enddate']:
                                parsed_date = parse_date(row['enddate'])
                                if parsed_date is None:
                                    _validation_error.append("Invalid end date format")
                                else:
                                    row['enddate'] = parsed_date


                        # Append error record if found
                        if _validation_error:
                            row['ValidationError'] = ','.join(
                                _validation_error)
                            row['ErrorRowNumber'] = str(row_number)
                            _error_rows_arr.append(row)
                        else:
                            _valid_rows_arr.append(row)

                        # Exit processing, if max error records limit reached.
                        if len(_error_rows_arr) > self.err_records_max:
                            write_to_error_file(self.error_file_header,
                                error_file_path, _error_rows_arr)
                            logger.error(
                                'Exiting encounter de-identifying as max errors records limit reached - {}', str(self.err_records_max))
                            raise MaxErrorCountReachedError(
                                "Exiting function as max errors records limit reached - " + str(self.err_records_max))

                        # Write valid records to file, if batch size reached.
                        if len(_valid_rows_arr) == self.write_batch_size:
                            write_to_deid_file(self.deid_header,
                                _valid_rows_arr, deid_file_path, config.csv_delimiter)
                            _valid_rows_arr = []

                        # Print progress
                        bar()

                # Writer valid records to file (remaining records when given batch size does not meet)
                write_to_deid_file(self.deid_header,
                              _valid_rows_arr, deid_file_path, config.csv_delimiter)

                # Write error records to file
                write_to_error_file(self.error_file_header,error_file_path, _error_rows_arr)
            print('\n')
        except MaxErrorCountReachedError:
            raise
        except Exception as e:
            raise e



def do_deidentify(csv_file_path,config):
    """This methods contains housekeeping needs to be done before de-identifing encounter file.

    Args:
        csv_file_path (:obj:`str`, mandatory): Path to the input encounter csv file.

    Returns:
        str: Path to de-identified encounter file
        str: path to the error log file

    """

    if os.path.exists(csv_file_path):
        D = MozillaDeidEncounter(config.max_validation_error_count)
        deid_file_path = os.path.join(
            Path(csv_file_path).parent, "deid", 'encounters.csv')
        error_file_path = os.path.join(
            Path(csv_file_path).parent, "logs", 'error_deid_encounters.csv')

        # Delete deid and error file if already exists
        delete_file_if_exists(deid_file_path)
        delete_file_if_exists(error_file_path)

        mkParentDir(deid_file_path)
        mkParentDir(error_file_path)

        # Get patient mapping and encounter mapping
        patient_map = PatientMapping.get_patient_mapping(config)
        encounter_map = EncounterMapping.get_encounter_mapping(config)

        D.deidentify_encounter(config, patient_map, encounter_map, csv_file_path,
                               deid_file_path, error_file_path)

        return deid_file_path, error_file_path

    else:
        logger.error('File does not exist : {}', csv_file_path)
