#
# Copyright (c) 2020-2021 Massachusetts General Hospital. All rights reserved. 
# This program and the accompanying materials  are made available under the terms 
# of the Mozilla Public License v. 2.0 ( http://mozilla.org/MPL/2.0/) and under 
# the terms of the Healthcare Disclaimer.
#

import os
import csv
from datetime import datetime as DateTime
from i2b2_cdi.database.cdi_database_connections import I2b2crcDataSource
from Mozilla.exception.mozilla_cdi_database_error import CdiDatabaseError
from loguru import logger
from alive_progress import alive_bar
from pathlib import Path
from i2b2_cdi.common import delete_file_if_exists, mkParentDir, file_len
import codecs


class MozillaEncounterMapping:
    """The class provides the interface for de-identifying i.e. (mapping src encounter id to i2b2 generated encounter num) encounter file"""

    def __init__(self): 
        self.write_batch_size = 100
        self.new_encounter_map = {}
        now = DateTime.now()
        self.encounter_num = None
        self.import_time = now.strftime("%Y-%m-%d %H:%M:%S")
        self.bcp_header = ['ENCOUNTER_IDE', 'ENCOUNTER_IDE_SRC', 'PROJECT_ID', 'ENCOUNTER_NUM', 'PATIENT_IDE', 'PATIENT_IDE_SRC',
                           'ENCOUNTER_IDE_STATUS', 'UPLOAD_DATE', 'UPDATE_DATE', 'DOWNLOAD_DATE', 'IMPORT_DATE', 'SOURCESYSTEM_CD', 'UPLOAD_ID']

    def create_encounter_mapping(self, csv_file_path, encounter_mapping_file_path,config):  
        """This method creates encounter mapping, it checks if mapping already exists

        Args:
            csv_file_path (:obj:`str`, mandatory): Path to the encounter file.
            input_csv_delimiter (:obj:`str`, mandatory): Delimiter to be used while reading the file

        """
        logger.debug(
            'Creating encounter mapping from input file : {}', csv_file_path)
        try:
            # max lines
            max_line = file_len(csv_file_path)

            # Get max of encounter_num
            self.encounter_num = self.get_max_encounter_num(config)

            # Get existing encounter mapping
            encounter_map = get_encounter_mapping(config)

            # Read input csv file
            with codecs.open(csv_file_path, mode='r', encoding='utf-8-sig',errors='ignore') as csv_file:
                csv_reader = csv.DictReader(
                    csv_file, delimiter=config.csv_delimiter)
                csv_reader.fieldnames = [c.replace(
                    '-', '').replace('_', '').replace(' ', '').lower() for c in csv_reader.fieldnames]
                if 'encounterid' in csv_reader.fieldnames and 'mrn' in csv_reader.fieldnames:
                    row_number = 0
                    with alive_bar(max_line, bar='smooth') as bar:
                        for row in csv_reader:
                            row_number += 1

                            # Print progress
                            bar()

                            if not row['encounterid']:
                                continue
                            if not row['mrn']:
                                continue

                            # Get encounter_num if encounter already exists
                            encounter_num = self.check_if_encounter_exists(
                                row['encounterid'], encounter_map)

                            # Get next encounter_num if it does not exists
                            if encounter_num is None:

                                encounter_num = self.encounter_num+1
                                # Update the map cache
                                encounter_map.update(
                                    {row['encounterid']: encounter_num})
                                self.prepare_encounter_mapping(
                                    encounter_num, row['encounterid'], 'DEMO', row['mrn'])
            print('\n')
            from i2b2_cdi.encounter.encounter_mapping import EncounterMapping
            child_obj = EncounterMapping()
            child_obj.write_encounter_mapping(
                encounter_mapping_file_path, config.bcp_delimiter, config.source_system_cd, config.upload_id )
        except Exception as e:
            logger.error('Failed to genrate encounter mapping : {}', e)
            raise e

    def check_if_encounter_exists(self, encounter_id, encounter_map): 
        """This method checks if encounter mapping already exists in a database

        Args:
            encounter_id (:obj:`str`, mandatory): Src encounter id.
            encounter_map (:obj:`str`, mandatory): Encounter map that contains existing mapping.
        """
        encounter_num = None
        try:
            if encounter_id in encounter_map:
                encounter_num = encounter_map.get(encounter_id)
            return encounter_num
        except Exception as e:
            raise e
    
    def get_max_encounter_num(self,config): 
        """This method runs the query on encounter mapping to get max encounter_num.
        """
        encounter_num = None
        try:
            with I2b2crcDataSource(config) as cursor:
                query = 'select COALESCE(max(encounter_num), 0) as encounter_num from ENCOUNTER_MAPPING'
                cursor.execute(query)
                row = cursor.fetchone()
                encounter_num = row[0]
            return encounter_num
        except Exception as e:
            raise e

def create_encounter_mapping(csv_file_path,config): 
    """This methods contains housekeeping needs to be done before creating encounter mapping.

    Args:
        csv_file_path (:obj:`str`, mandatory): Path to the input encounter csv file.
    Returns:
        str: Path to converted bcp file
    """
    if os.path.exists(csv_file_path):
        D = MozillaEncounterMapping()
        
        encounter_mapping_file_path = os.path.join(
            Path(csv_file_path).parent, "deid", "bcp", 'encounter_mapping.bcp')

        # Delete bcp and error file if already exists
        delete_file_if_exists(encounter_mapping_file_path)
        mkParentDir(encounter_mapping_file_path)

        D.create_encounter_mapping(
            csv_file_path, encounter_mapping_file_path,config)
        return encounter_mapping_file_path
    else:
        logger.error('File does not exist : {}', csv_file_path)
 

def get_encounter_mapping(config): 
    """Get encounter mapping data from i2b2 instance"""
    encounter_map = {}
    try:
        logger.debug("Getting existing encounter mappings from database")
        query = 'SELECT encounter_ide, encounter_num FROM encounter_mapping'

        with I2b2crcDataSource(config) as cursor:
            cursor.execute(query)
            result = cursor.fetchall()
            if result:
                for row in result:
                    encounter_map.update({row[0]: row[1]})

        return encounter_map
    except Exception as e:
        raise CdiDatabaseError("Couldn't get data: {0}".format(str(e)))