"""SDV Modeler."""

import logging

import pandas as pd

from sdv.models.copulas import GaussianCopula

LOGGER = logging.getLogger(__name__)


class Modeler:
    """Modeler class.

    The Modeler class applies the CPA algorithm recursively over all the tables
    from the dataset.

    Args:
        metadata (Metadata):
            Dataset Metadata.
        model (type):
            Class of model to use. Defaults to ``sdv.models.copulas.GaussianCopula``.
        model_kwargs (dict):
            Keyword arguments to pass to the model. Defaults to ``None``.
    """

    def __init__(self, metadata, model=GaussianCopula, model_kwargs=None):
        self.models = dict()
        self.metadata = metadata
        self.model = model
        self.model_kwargs = dict() if model_kwargs is None else model_kwargs
        self.table_sizes = dict()

    def _get_extension(self, child_name, child_table, foreign_key):
        """Generate list of extension for child tables.

        Each element of the list is generated for one single children.
        That dataframe should have as ``index.name`` the ``foreign_key`` name, and as index
        it's values.

        The values for a given index are generated by flattening a model fitted with
        the related data to that index in the children table.

        Args:
            parent (str):
                Name of the parent table.
            children (set[str]):
                Names of the children.
            tables (dict):
                Previously processed tables.

        Returns:
            pandas.DataFrame
        """
        extension_rows = list()
        foreign_key_values = child_table[foreign_key].unique()
        child_table = child_table.set_index(foreign_key)
        child_primary = self.metadata.get_primary_key(child_name)

        for foreign_key_value in foreign_key_values:
            child_rows = child_table.loc[[foreign_key_value]]
            if child_primary in child_rows.columns:
                del child_rows[child_primary]

            num_child_rows = len(child_rows)

            model = self.model(**self.model_kwargs)
            model.fit(child_rows)
            row = model.get_parameters()
            row['child_rows'] = num_child_rows

            row = pd.Series(row)
            row.index = '__' + child_name + '__' + row.index
            extension_rows.append(row)

        return pd.DataFrame(extension_rows, index=foreign_key_values)

    def cpa(self, table_name, tables, foreign_key=None):
        """Run the CPA algorithm over the indicated table and its children.

        Args:
            table_name (str):
                Name of the table to model.
            tables (dict):
                Dict of original tables.
            foreign_key (str):
                Name of the foreign key that references this table. Used only when applying
                CPA on a child table.

        Returns:
            pandas.DataFrame:
                table data with the extensions created while modeling its children.
        """
        LOGGER.info('Modeling %s', table_name)

        if tables:
            table = tables[table_name]
        else:
            table = self.metadata.load_table(table_name)

        self.table_sizes[table_name] = len(table)

        extended = self.metadata.transform(table_name, table)

        primary_key = self.metadata.get_primary_key(table_name)
        if primary_key:
            extended.index = table[primary_key]
            for child_name in self.metadata.get_children(table_name):
                child_key = self.metadata.get_foreign_key(table_name, child_name)
                child_table = self.cpa(child_name, tables, child_key)
                extension = self._get_extension(child_name, child_table, child_key)
                extended = extended.merge(extension, how='left',
                                          right_index=True, left_index=True)
                extended['__' + child_name + '__child_rows'].fillna(0, inplace=True)

        model = self.model(**self.model_kwargs)
        model.fit(extended)
        self.models[table_name] = model

        if primary_key:
            extended.reset_index(inplace=True)

        if foreign_key:
            extended[foreign_key] = table[foreign_key]

        return extended

    def model_database(self, tables=None):
        """Run CPA algorithm on all the tables of this dataset.

        Args:
            tables (dict):
                Optional. Dictinary containing the tables of this dataset.
                If not given, the tables will be loaded using the dataset
                metadata specification.
        """
        for table_name in self.metadata.get_tables():
            if not self.metadata.get_parents(table_name):
                self.cpa(table_name, tables)

        LOGGER.info('Modeling Complete')
