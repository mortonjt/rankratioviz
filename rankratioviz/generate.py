#!/usr/bin/env python3
# ----------------------------------------------------------------------------
# Copyright (c) 2018--, rankratioviz development team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file LICENSE.txt, distributed with this software.
#
# Generates two JSON files: one for a rank plot and one for a sample
# scatterplot of log ratios.
#
# A lot of the code for processing input data in this file was based on code
# by Jamie Morton, some of which is now located in ipynb/Figure3.ipynb in
# https://github.com/knightlab-analyses/reference-frames.
# ----------------------------------------------------------------------------

import json
import os
from shutil import copyfile, copytree
import pandas as pd
import altair as alt


def matchdf(df1, df2):
    """Filters both DataFrames to just the rows of their shared indices.

       Derived from gneiss.util.match() (https://github.com/biocore/gneiss).
    """

    idx = set(df1.index) & set(df2.index)
    return df1.loc[idx], df2.loc[idx]


def assert_df_indices_unique(df):
    """Assert that the index of this DataFrame consists of unique IDs."""
    assert len(df.index.unique()) == df.shape[0]


def process_input(feature_ranks, sample_metadata, biom_table,
                  feature_metadata=None):
    """Loads the ordination file, BIOM table, and optionally taxonomy data."""

    # Assert that the feature IDs and sample IDs contain only unique IDs.
    # (This doesn't check that there aren't any identical IDs between the
    # feature and sample IDs, but we shouldn't be using sample IDs to query
    # feature IDs anyway. And besides, I think that should technically be
    # allowed.)
    assert_df_indices_unique(feature_ranks)
    assert_df_indices_unique(sample_metadata)

    table = biom_table.to_dataframe().to_dense()
    # Match features to BIOM table, and then match samples to BIOM table.
    # This should bring us to a point where every feature/sample is
    # supported in the BIOM table. (Note that the input BIOM table might
    # contain features or samples that are not included in feature_ranks or
    # sample_metadata, respectively -- this is totally fine. The opposite,
    # though, is a big no-no.)
    table, V = matchdf(table, feature_ranks)
    # Assert that every ranked feature was present in the BIOM table.
    assert V.shape[0] == feature_ranks.shape[0]

    table, U = matchdf(table.T, sample_metadata)
    # Assert that every sample was present in the BIOM table.
    assert U.shape[0] == sample_metadata.shape[0]

    labelled_feature_ranks = feature_ranks.copy()
    # Now that we've matched up the BIOM table with the feature ranks and
    # sample metadata, we're pretty much done. If the user passed in feature
    # metadata corresponding to taxonomy information, then we use that to
    # update the feature IDs to include that metadata. (This can help out in
    # the searching part of the visualization, but it isn't necessary.)
    if feature_metadata is not None:
        # Match features with feature metadata
        matched_feature_metadata, _ = matchdf(feature_metadata, V)
        # This is how we can check that every feature is present in the
        # feature metadata. This check is disabled because it can be useful to
        # look at features that don't have any assigned metadata. However, if
        # we ever decide to enforce that all features must have corresponding
        # metadata values, this is how we'd do that.
        # assert V.shape[0] == feature_ranks.shape[0]

        no_metadata_feature_ids = (set(feature_ranks.index)
                                   - set(matched_feature_metadata.index))

        # Create nice IDs for each feature with associated metadata.
        new_feature_ids = pd.Series(index=feature_ranks.index)
        for feature_row in matched_feature_metadata.iterrows():
            str_vals = [str(v) for v in feature_row[1].values]
            id_prefix = feature_row[0] + '|'
            new_feature_ids[feature_row[0]] = id_prefix + '|'.join(str_vals)
        # Features with no associated metadata just get their old IDs.
        for feature_row_id in no_metadata_feature_ids:
            new_feature_ids[feature_row_id] = feature_row_id
        # Now we have our nice IDs. Update labelled_feature_ranks and the
        # table accordingly.
        labelled_feature_ranks.index = new_feature_ids
        # Update the table's columns (corresponding to features) to match the
        # new feature IDs.
        # First, we define new_feature_ids_tbl, which is just a list of the
        # values of new_feature_ids sorted to match the order of the
        # columns in the BIOM table.
        new_feature_ids_tbl = [new_feature_ids[fc] for fc in table.columns]
        # Then, we can just set the table's columns to this in order to augment
        # existing columns' IDs with feature metadata where available.
        table.columns = new_feature_ids_tbl

    # Small sanity test: check that incorporating feature metadata didn't
    # accidentally make some feature IDs the same.
    #
    # Assuming each feature ID is preserved in the new ID this should never be
    # the case, but in case we modify the above code this will still ensure
    # that something isn't going horribly wrong somehow.
    assert_df_indices_unique(labelled_feature_ranks)

    return labelled_feature_ranks, table


def gen_rank_plot(V):
    """Generates altair.Chart object describing the rank plot.

    Arguments:

    V: feature ranks

    Returns:

    JSON describing altair.Chart for the rank plot.
    """

    # TODO make a copy of V first, just to be extra safe
    # Get stuff ready for the rank plot
    # First off, convert all rank column IDs to strings (since Altair gets
    # angry if you pass in ints as column IDs). This is a problem with
    # OrdinationResults files, since just getting the raw column IDs gives int
    # values (0 for the first column, 1 for the second column, etc.)
    V.columns = ["Rank " + str(c) for c in V.columns]

    # The default rank column is just whatever the first rank is. This is what
    # the rank plot will use when it's first drawn.
    default_rank_col = V.columns[0]

    # Sort the ranked features in ascending order by their first rank.
    # NOTE that until this point we've treated the actual rank values as just
    # "objects", as far as pandas is concerned. However, if we continue to
    # treat them as objects when sorting them, we'll get a list of feature
    # ranks in lexicographic order... which is not what we want.
    V[default_rank_col] = pd.to_numeric(V[default_rank_col])
    rank_vals = V.sort_values(by=[default_rank_col])

    # "x" keeps track of the sorted order of the ranks. It's just a range of
    # [0, F), where F = the number of ranked features.
    x = range(rank_vals.shape[0])

    # Set default classification of every taxon to "None"
    # (This value will be updated when a taxon is selected in the rank plot as
    # part of the numerator, denominator, or both parts of the current log
    # ratio.)
    classification = pd.Series(index=rank_vals.index).fillna("None")

    # Start populating the DataFrame we'll pass into Altair as the main source
    # of data for the rank plot.
    rank_data = pd.DataFrame({'x': x, "Classification": classification})

    # Merge that DataFrame with the actual rank values. Their indices should be
    # identical, since we constructed rank_data based on rank_vals.
    rank_data = pd.merge(rank_data, rank_vals, left_index=True,
                         right_index=True)

    # Replace "index" with "Feature ID". looks nicer in the visualization :)
    rank_data.rename_axis("Feature ID", axis="index", inplace=True)
    rank_data.reset_index(inplace=True)
    # NOTE: The default size value of mark_bar() causes an apparent offset in
    # the interval selection (we're not using that right now, except for the
    # .interactive() thing, though, so I don't think this is currently
    # relevant).
    #
    # Setting size to 1.0 fixes this; using mark_rule() also fixes this,
    # probably because the lines in rule charts are just lines with a width
    # of 1.0.
    rank_chart = alt.Chart(
        rank_data,
        title="Feature Ranks"
    ).mark_bar().encode(
        x=alt.X('x', title="Features", type="quantitative"),
        y=alt.Y(default_rank_col, type="quantitative"),
        color=alt.Color(
            "Classification",
            scale=alt.Scale(
                domain=["None", "Numerator", "Denominator", "Both"],
                range=["#e0e0e0", "#f00", "#00f", "#949"]
            )
        ),
        size=alt.value(1.0),
        tooltip=["x", "Classification", "Feature ID"]
    ).configure_axis(
        # Done in order to differentiate "None"-classification taxa from grid
        # lines
        gridOpacity=0.35
    ).interactive()

    rank_chart_json = rank_chart.to_dict()
    rank_ordering = "rankratioviz_rank_ordering"
    rank_chart_json["datasets"][rank_ordering] = list(V.columns)
    return rank_chart_json


def gen_sample_plot(table, metadata):
    """Generates altair.Chart object describing the sample scatterplot.

    Arguments:

    table: pandas DataFrame describing taxon abundances for each sample.
    metadata: pandas DataFrame describing metadata for each sample.

    Returns:

    JSON describing altair.Chart for the sample plot.
    """

    # Used to set x-axis and color
    default_metadata_col = metadata.columns[0]

    # Since we don't bother setting a default log ratio, we set the balance for
    # every sample to NaN so that Altair will filter them out (producing an
    # empty scatterplot by default, which makes sense).
    balance = pd.Series(index=table.index).fillna(float('nan'))
    df_balance = pd.DataFrame({'rankratioviz_balance': balance})
    # At this point, "data" is a DataFrame with its index as sample IDs and
    # one column ("balance", which is solely NaNs).
    sample_metadata = pd.merge(df_balance, metadata, left_index=True,
                               right_index=True)
    # TODO note dropped samples from this merge (by comparing data with
    # metadata and table) and report them to user (#54).

    # "Reset the index" -- make the sample IDs a column (on the leftmost side)
    # First we rename the index "Sample ID", just on the off chance that
    # there's a metadata column called "index".
    # NOTE that there shouldn't be a metadata column called Sample ID or
    # something like that, since that should've been used in the merge with
    # df_balance above (and "Sample ID" follows the Q2 metadata conventions for
    # an "Identifier Column" name).
    sample_metadata.rename_axis("Sample ID", axis="index", inplace=True)
    sample_metadata.reset_index(inplace=True)

    # Make note of the column IDs in the "table" DataFrame.
    # This constructs a dictionary mapping the feature (column) IDs to their
    # integer indices (just the range of [0, f), where f is the number of
    # features in the BIOM table).
    # We'll preserve this mapping in the sample plot JSON.
    sample_features = table.copy()
    feature_ids = sample_features.columns
    feature_cn2si = {}
    feature_columns_range = range(len(feature_ids))
    feature_columns_str_range = [str(i) for i in feature_columns_range]
    for j in feature_columns_range:
        # (Altair doesn't seem to like accepting ints as column IDs.)
        feature_cn2si[feature_ids[j]] = feature_columns_str_range[j]

    # Now, we replace column IDs (which could include thousands of taxon
    # IDs) with just the integer indices from before.
    #
    # This can save *a lot* of space in the JSON file for the sample plot,
    # since each column name is referenced once for each sample (and
    # 50 samples * (~3000 taxonomies) * (~50 characters per ID)
    # comes out to 7.5 MB, which is an underestimate).
    sample_features.columns = feature_columns_str_range

    # Create sample plot in Altair.
    # If desired, we can make this interactive by adding .interactive() to the
    # alt.Chart declaration (but we don't do that currently since it makes
    # changing the scale of the chart smoother IIRC)
    sample_chart = alt.Chart(
        sample_metadata,
        title="Log Ratio of Abundances in Samples"
    ).mark_circle().encode(
        alt.X(default_metadata_col),
        alt.Y("rankratioviz_balance", title="log(Numerator / Denominator)"),
        color=alt.Color(
            default_metadata_col,
            # This is a temporary measure. Eventually the type should be
            # user-configurable -- some of the metadata fields might actually
            # be nominal data, but many will likely be numeric (e.g. SCORAD for
            # dermatitis). Exposing this to the user in the visualization
            # interface is probably the best option, for when arbitrary amounts
            # of metadata can be passed.
            type="nominal"
        ),
        tooltip=["Sample ID"]
    )

    # Save the sample plot JSON. Some notes:
    # -From Altair (and Vega)'s perspective, the only "dataset" that directly
    #  connects to the chart is sample_metadata. This dataset contains the
    #  "Sample ID" and "rankratioviz_balance" columns, in addition to all of
    #  the sample metadata columns provided in the input sample metadata.
    # -All of the feature counts for each sample (that is, taxon/metabolite
    #  abundances) are located in the features_ds dataset. These feature counts
    #  can be drawn on in the JS application when computing log ratios, and
    #  this lets us search through all available taxon IDs/etc. without
    #  having to worry about accidentally mixing up metadata and feature
    #  counts.
    # -Since feature IDs can be really long (e.g. in the case where the feature
    #  ID is an entire taxonomy), we convert each feature ID to a string
    #  integer and refer to that feature by its string integer ID. We store a
    #  mapping relating actual feature IDs to their string integer IDs under
    #  the col_ids_ds dataset, which is how we'll determine what to show to
    #  the user (and link features on the rank plot with feature counts in
    #  the sample plot) in the JS code.
    sample_chart_json = sample_chart.to_dict()
    col_ids_ds = "rankratioviz_feature_col_ids"
    features_ds = "rankratioviz_feature_counts"
    sample_chart_json["datasets"][col_ids_ds] = feature_cn2si
    sample_chart_json["datasets"][features_ds] = sample_features.to_dict()
    return sample_chart_json


def gen_visualization(V, processed_table, df_sample_metadata, output_dir):
    """Creates a rankratioviz visualization. This function should be callable
       from both the QIIME 2 and standalone rankratioviz scripts.

       Returns:

       index_path: a path to the index.html file for the output visualization.
                   This is needed when calling q2templates.render().
    """
    rank_plot_json = gen_rank_plot(V)
    sample_plot_json = gen_sample_plot(processed_table, df_sample_metadata)
    os.makedirs(output_dir, exist_ok=True)
    # copy files for the visualization
    loc_ = os.path.dirname(os.path.realpath(__file__))
    # NOTE: We can just join loc_ with support_files/, since support_files/ is
    # located within the same directory as generate.py. Previously (when this
    # code was contained in q2/_method.py and scripts/_plot.py), I joined loc_
    # with .. and then with support_files since we had to first navigate up to
    # the directory containing generate.py and support_files/. Now, we don't
    # have to do that any more.
    support_files_loc = os.path.join(loc_, 'support_files')
    index_path = None
    for file_ in os.listdir(support_files_loc):
        if file_ != '.DS_Store':
            copy_func = copyfile
            # If we hit a directory in support_files/, just copy the entire
            # directory to our destination using shutil.copytree()
            if os.path.isdir(os.path.join(support_files_loc, file_)):
                copy_func = copytree
            copy_func(
                os.path.join(support_files_loc, file_),
                os.path.join(output_dir, file_)
            )
        if 'index.html' in file_:
            index_path = os.path.join(output_dir, file_)

    if index_path is None:
        # This should never happen -- assuming rankratioviz has been installed
        # fully, i.e. with a complete set of support_files/ -- but we handle it
        # here just in case.
        raise FileNotFoundError("Couldn't find index.html in support_files/")
    # write new files
    rank_plot_loc = os.path.join(output_dir, 'rank_plot.json')
    sample_plot_loc = os.path.join(output_dir, 'sample_plot.json')
    # For reference: https://stackoverflow.com/a/12309296
    with open(rank_plot_loc, "w") as jf:
        json.dump(rank_plot_json, jf)
    with open(sample_plot_loc, "w") as jf2:
        json.dump(sample_plot_json, jf2)
    return index_path
