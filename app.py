import os
from flask import Flask, request, render_template, send_file, redirect, url_for
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

uploaded_files = []
df_dict = {}

@app.route('/', methods=['GET', 'POST'])
def index():
    global uploaded_files, df_dict
    if request.method == 'POST':
        files = request.files.getlist('files')
        if len(files) < 2:
            return "Upload at least 2 files"

        uploaded_files = []
        df_dict = {}

        for file in files:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            ext = filename.split('.')[-1]

            if ext.lower() == 'csv':
                df = pd.read_csv(filepath)
            else:
                df = pd.read_excel(filepath, engine='openpyxl')

            df_dict[filename] = df
            uploaded_files.append(filename)

        return redirect(url_for('select_columns'))

    return render_template('index.html')

@app.route('/select-columns', methods=['GET', 'POST'])
def select_columns():
    if request.method == 'POST':
        common_mapping = request.form.getlist('common_mapping')  # example format: 'file1:colA,file2:colB'
        compare_cols = request.form.getlist('compare_columns')
        view_only_cols = request.form.getlist('view_columns')

        return redirect(url_for('compare',
                                common_mapping='|'.join(common_mapping),
                                compare_cols=','.join(compare_cols),
                                view_cols=','.join(view_only_cols)))

    columns_map = {fname: list(df.columns) for fname, df in df_dict.items()}
    return render_template('select_columns.html', columns_map=columns_map)

@app.route('/compare')
def compare():
    common_mapping = request.args.get('common_mapping').split('|')
    compare_cols = request.args.get('compare_cols').split(',') if request.args.get('compare_cols') else []
    view_cols = request.args.get('view_cols').split(',') if request.args.get('view_cols') else []

    # Build rename map per file
    rename_maps = {}
    common_keys = []
    for mapping in common_mapping:
        parts = mapping.split(',')  # e.g. ['file1:ID', 'file2:id']
        standard_col = parts[0].split(':')[1]  # Use the first column name as standard
        common_keys.append(standard_col)
        for part in parts:
            fname, col = part.split(':')
            if fname not in rename_maps:
                rename_maps[fname] = {}
            rename_maps[fname][col] = standard_col

    base_fname = uploaded_files[0]
    base_df = df_dict[base_fname].rename(columns=rename_maps.get(base_fname, {})).copy()
    base_df = base_df[common_keys + compare_cols + view_cols]

    for fname in uploaded_files[1:]:
        df = df_dict[fname].rename(columns=rename_maps.get(fname, {}))
        df = df[common_keys + compare_cols + view_cols]
        suffix = os.path.splitext(fname)[0]
        base_df = pd.merge(base_df, df, on=common_keys, how='outer', suffixes=('', f'_{suffix}'))

    # Highlight differences in compare columns
    diff_cols = []
    for fname in uploaded_files[1:]:
        suffix = os.path.splitext(fname)[0]
        for col in compare_cols:
            col_compare = f'{col}_{suffix}'
            if col_compare in base_df.columns:
                diff_cols.append(col_compare)

    def highlight_diff(val, row_idx, col_name):
        base_col = col_name.rsplit('_', 1)[0]
        if base_col not in base_df.columns:
            return ''
        base_val = base_df.iloc[row_idx][base_col]
        return 'color: red' if pd.notna(val) and val != base_val else ''

    styled_df = base_df.style

    for col_name in diff_cols:
        styled_df = styled_df.apply(
            lambda col_vals: [
                highlight_diff(val, i, col_name)
                for i, val in enumerate(col_vals)
            ],
            axis=0,
            subset=[col_name]
        )

    styled_html = styled_df.to_html()

    # Export to Excel
    output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'comparison_result.xlsx')
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        base_df.to_excel(writer, index=False, sheet_name='Comparison')
        workbook = writer.book
        worksheet = writer.sheets['Comparison']

        red_format = workbook.add_format({'font_color': 'red'})

        for row in range(1, len(base_df) + 1):
            for col_idx, col in enumerate(base_df.columns):
                if col in diff_cols:
                    value = base_df.iloc[row - 1, col_idx]
                    base_col = col.rsplit('_', 1)[0]
                    if base_col in base_df.columns:
                        base_value = base_df.iloc[row - 1, base_df.columns.get_loc(base_col)]
                        if pd.notna(value) and value != base_value:
                            worksheet.write(row, col_idx, value, red_format)

    return render_template('compare.html', table=styled_html, download_link='/download')

@app.route('/download')
def download():
    return send_file(os.path.join(app.config['UPLOAD_FOLDER'], 'comparison_result.xlsx'), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
