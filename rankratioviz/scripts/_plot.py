# ----------------------------------------------------------------------------
# Copyright (c) 2018--, rankratioviz development team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE.txt, distributed with this software.
# ----------------------------------------------------------------------------
from biom import load_table
import pandas as pd
import click
from rankratioviz.generate import process_input, gen_visualization
from rankratioviz._rank_processing import rank_file_to_df


@click.command()
@click.option('-r', '--ranks', required=True,
              help="Differentials output from songbird or Ordination output"
                   + " from DEICODE.")
@click.option('-t', '--table', required=True,
              help="BIOM table describing taxon/metabolite sample abundances.")
@click.option('-fm', '--feature-metadata', default=None,
              help="Feature metadata file.")
@click.option('-sm', '--sample-metadata', required=True,
              help="Sample metadata file.")
@click.option('-o', '--output-dir', required=True,
              help="Location of output files.")
def plot(ranks: str, table: str, sample_metadata: str, feature_metadata: str,
         output_dir: str) -> None:
    """Generates a plot of ranked taxa/metabolites and their abundances."""

    def read_metadata(md_file_loc):
        return pd.read_csv(md_file_loc, index_col=0, sep='\t')

    loaded_biom = load_table(table)
    df_sample_metadata = read_metadata(sample_metadata)
    feature_ranks = rank_file_to_df(ranks)

    df_feature_metadata = None
    if feature_metadata is not None:
        df_feature_metadata = read_metadata(feature_metadata)

    V, processed_table = process_input(feature_ranks, df_sample_metadata,
                                       loaded_biom, df_feature_metadata)
    gen_visualization(V, processed_table, df_sample_metadata, output_dir)


if __name__ == '__main__':
    plot()
