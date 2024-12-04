#!/opt/homebrew/bin/python3

import csv
import os
import sqlite3
import sys


# Superclass for all exceptions defined in this file
class Csv2SqliteException(Exception):
    pass

class EmptyCsvFileException(Csv2SqliteException):
    pass

class InconsistentNumCsvColumnsException(Csv2SqliteException):
    pass

class MissingCsvColumnsException(Csv2SqliteException):
    pass

class TooManyPrimaryKeysException(Csv2SqliteException):
    pass


# To be used with "with", see https://stackoverflow.com/questions/865115/how-do-i-correctly-clean-up-a-python-object
class TableOp():
    def __init__(self, connection, table) -> None:
        self.connection = connection
        self.table = table

    #
    # "with" setup
    #
    def __enter__(self):
        self.cursor = self.connection.cursor()

        # Get the columns schema
        self.cursor.execute(f'PRAGMA table_info({self.table})')
        self.columns_schema = [TableOp._columnSchemaFromInfo(row) for row in self.cursor.fetchall()]
        self.n_columns = len(self.columns_schema)

        # Prepare info of non-primary key columns
        # Note: composite primary keys are not supported for now
        self.non_pk_columns_schema = [column for column in self.columns_schema if column['is_primary_key'] == 0]

        # Number of primary keys sanity check
        if self.n_columns > len(self.non_pk_columns_schema) + 1:
            raise TooManyPrimaryKeysException

        return self

    #
    # "with" cleanup
    #
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.cursor.close()

    #
    # Convert a list of strings defining a column (as in the output of
    # "PRAGMA table_info") into a dictionary
    #
    @staticmethod
    def _columnSchemaFromInfo(column_info):
        return {
            'id': column_info[0],
            'name': column_info[1],
            'type': column_info[2],
            'is_not_null': column_info[3],
            'default_value': column_info[4],
            'is_primary_key': column_info[5],
        }

    #
    # Convert a string to its proper type based on its column type in the schema
    #
    @staticmethod
    def _valueFromString(string, column_defintion):
        value = string  # default
        match column_defintion['type']:
            case 'NULL':
                value = None
            case 'INTEGER':
                value = int(string)
            case 'REAL':
                value = float(string)
            case _:  # TEXT, BLOB
                pass
        return value

    #
    # Convert a row of strings to the appropriate types
    #
    @staticmethod
    def _valuesFromStrings(row, columns_defintion):
        return [TableOp._valueFromString(string, column_definition) for string, column_definition in zip(row, columns_defintion)]

    #
    # Convert a list of parameters to a string which can be used in a query
    #
    @staticmethod
    def _parameterString(parameters):
        return '(' + ', '.join(parameters) + ')'

    #
    # Bulk imports all the rows in a csv file into 'self.table'
    #
    def bulkCsvImport(self, csv_path):
        # Read all the rows of the csv file into a list
        with open(csv_path, 'r', encoding='utf-8') as csv_file:
            csv_reader = csv.reader(csv_file)
            rows = list(csv_reader)

        # Verify that some rows were retrieved
        if len(rows) == 0:
            raise EmptyCsvFileException

        # Verify that the number of columns is uniform across all rows
        # Note: a primary key may not be specified
        n_params = len(rows[0])
        for i in range(1, len(rows)):    # more efficient than looping through rows[1:], as slicing involves copying
            if len(rows[i]) != n_params:
                raise InconsistentNumCsvColumnsException

        # Execute the query
        placeholders = ['?'] * n_params
        if n_params == self.n_columns:  # the csv file supplies values for all the columns
            column_names = placeholders
            columns_used = self.columns_schema
        elif n_params == self.n_columns - 1:  # only the primary key values should be missing
            column_names = [column['name'] for column in self.non_pk_columns_schema]
            columns_used = self.non_pk_columns_schema
        else:
            raise MissingCsvColumnsException
        column_names_str = TableOp._parameterString(column_names)
        placeholders_str = TableOp._parameterString(placeholders)
        query = f'INSERT INTO {self.table}{column_names_str} VALUES{placeholders_str}'
        values = [TableOp._valuesFromStrings(row, columns_used) for row in rows]
        self.cursor.executemany(query, values)


# To be used with "with", see https://stackoverflow.com/questions/865115/how-do-i-correctly-clean-up-a-python-object
class SqliteDb():
    def __init__(self, dbfile):
        self.dbfile = dbfile

    #
    # "with" setup
    #
    def __enter__(self):
        self.connection = sqlite3.connect(self.dbfile)
        return self

    #
    # "with" cleanup
    #
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.connection.close()

    def newTableOp(self, table):
        return TableOp(self.connection, table)


def usage(command_path):
    command_name = os.path.basename(command_path)
    print(f'Usage: {command_name} database_file table_name csv_file')
    sys.exit(1)


if __name__ == '__main__':
    command = sys.argv[0]
    if len(sys.argv) != 4:
        usage(command)
    with SqliteDb(sys.argv[1]) as db:
        with db.newTableOp(sys.argv[2]) as op:
            op.bulkCsvImport(sys.argv[3])