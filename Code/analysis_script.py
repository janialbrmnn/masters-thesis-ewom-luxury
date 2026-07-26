"""
analysis_script.py
==================
Statistical analysis for:
  "A Comparative Analysis of Consumer Value Perception in eWOM
   Across Heritage and Contemporary Luxury Brands"

Author : Jani Henrik Albermann
Script : Produces all three analytical layers described in Section 4
         of the thesis and exports results to thesis_analysis_v2.xlsx


LIBRARIES USED
--------------
  pandas       : data loading, merging, grouping
  numpy        : mathematical operations (log, etc.)
  scipy.stats  : Mann-Whitney U exact test
  statsmodels  : OLS regression with robust standard errors, VIF, Cook's D
  openpyxl     : writing Excel output
"""

import os
import pandas as pd
import numpy as np
from scipy.stats import mannwhitneyu
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor, OLSInfluence
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — file paths and brand prices
# ─────────────────────────────────────────────────────────────────────────────

# Paths
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))  # 04_Analysis/
DATA_DIR   = os.path.join(BASE_DIR, '..', '03_Data')
OUTPUT_DIR = BASE_DIR

LIWC_FILE  = os.path.join(DATA_DIR, 'LIWC-22 Results - liwc22_input_v04_clean - LIWC Analysis.csv')
CLEAN_FILE = os.path.join(DATA_DIR, 'reddit_data_v04_clean.csv')
OUTPUT_XLS = os.path.join(OUTPUT_DIR, 'thesis_analysis_v2.xlsx')

# Entry-level retail prices in EUR (European boutique list price, verified 2024-2025)
# Heritage brands
# Contemporary brands
PRICES = {
    'PatekPhilippe':       30000,   # Calatrava ref. 5196G
    'rolex':                6000,   # Oyster Perpetual 36mm
    'ALangeSohne':         12000,   # Saxonia Thin
    'VacheronConstantin':  18000,   # Patrimony 40mm
    'IWCSchaffhausen':      4200,   # Portofino Automatic
    'AudemarsPiguet':      38000,   # Royal Oak Selfwinding 41mm (ref. 15510ST)
    'Hublot':               5200,   # Classic Fusion 42mm
    'RichardMille':        85000,   # RM 010
    'FranckMuller':         5800,   # Curvex Master
    'MBandF':              44000,   # HM1
}

ENTRY_MODELS = {
    'PatekPhilippe':      'Calatrava ref. 5196G',
    'rolex':               'Oyster Perpetual 36mm',
    'ALangeSohne':        'Saxonia Thin',
    'VacheronConstantin': 'Patrimony 40mm',
    'IWCSchaffhausen':    'Portofino Automatic',
    'AudemarsPiguet':     'Royal Oak Selfwinding 41mm (ref. 15510ST)',
    'Hublot':             'Classic Fusion 42mm',
    'RichardMille':       'RM 010',
    'FranckMuller':       'Curvex Master',
    'MBandF':             'HM1',
}

DVS_PRIMARY = ['Analytic', 'Clout', 'Authentic', 'money']
DVS_ALL     = DVS_PRIMARY + ['Tone']


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Load and merge data
# ─────────────────────────────────────────────────────────────────────────────

print("Loading data...")
liwc  = pd.read_csv(LIWC_FILE)
clean = pd.read_csv(CLEAN_FILE)

# Join LIWC scores onto Reddit post metadata by post ID
df = clean[['item_id', 'brand_id', 'brand_nature', 'created_date']].merge(
    liwc[['Filename', 'WC', 'Analytic', 'Clout', 'Authentic', 'Tone', 'money']],
    left_on='item_id', right_on='Filename', how='inner'
)
df['created_date'] = pd.to_datetime(df['created_date'])

# Add derived columns
df['ln_WC']     = np.log(df['WC'].clip(lower=1))          # log word count (Layer 3 control)
df['price_eur'] = df['brand_id'].map(PRICES)
df['ln_price']  = np.log(df['price_eur'])
df['BN']        = (df['brand_nature'] == 'Heritage').astype(int)  # 1 = Heritage, 0 = Contemporary

print(f"  Posts loaded: {len(df):,}")
print(f"  Brands: {sorted(df['brand_id'].unique())}")

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Build brand-level dataset (10 rows, one per brand)
# ─────────────────────────────────────────────────────────────────────────────

bm = df.groupby(['brand_id', 'brand_nature'])[DVS_ALL].mean().reset_index()
bm['n_posts']     = df.groupby(['brand_id', 'brand_nature']).size().values
bm['price_eur']   = bm['brand_id'].map(PRICES)
bm['entry_model'] = bm['brand_id'].map(ENTRY_MODELS)
bm['ln_price']    = np.log(bm['price_eur'])
bm['BN']          = (bm['brand_nature'] == 'Heritage').astype(int)

# Separate heritage and contemporary groups
h = bm[bm['BN'] == 1]   # Heritage brands (n=5)
c = bm[bm['BN'] == 0]   # Contemporary brands (n=5)


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def rank_biserial(u, n1, n2):
    """
    Signed rank-biserial r.
    Positive value means the first group (g1) tends to score higher.
    Formula: r = 2U/(n1*n2) - 1
    """
    return round(2 * u / (n1 * n2) - 1, 3)


def holm_bonferroni(p_values):
    """Apply Holm-Bonferroni correction to a list of p-values (sorted ascending)."""
    m = len(p_values)
    adj = []
    for i in range(m):
        corrected = min(p_values[j] * (m - j) for j in range(i, m))
        adj.append(min(round(corrected, 4), 1.0))
    return adj


def run_layer2_ols(dv, data):
    """
    OLS regression at brand level (n=10):
        DV ~ BN(Heritage=1) + ln(Price)
    Returns HC2-robust results, VIF, and Cook's distances.
    """
    y = data[dv].values
    X = sm.add_constant(data[['BN', 'ln_price']].values)
    model    = sm.OLS(y, X)
    res_std  = model.fit()                 # standard fit for Cook's distance
    res_hc2  = model.fit(cov_type='HC2')  # HC2 robust SEs for inference

    X_pred = sm.add_constant(data[['BN', 'ln_price']].values)
    vif_bn    = variance_inflation_factor(X_pred, 1)
    vif_price = variance_inflation_factor(X_pred, 2)

    cooks = OLSInfluence(res_std).cooks_distance[0]
    return res_hc2, round(vif_bn, 2), round(vif_price, 2), cooks


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1 — Mann-Whitney U tests
# ─────────────────────────────────────────────────────────────────────────────

print("\nLayer 1: Mann-Whitney U tests...")

mw_rows = []

# For each hypothesis, g1 is the group predicted to score HIGHER
for hyp, dv, g1, g2, direction in [
    ('H1a', 'Clout',     c['Clout'].values,     h['Clout'].values,     'Contemporary > Heritage'),
    ('H1b', 'money',     c['money'].values,     h['money'].values,     'Contemporary > Heritage'),
    ('H2a', 'Analytic',  h['Analytic'].values,  c['Analytic'].values,  'Heritage > Contemporary'),
    ('H2b', 'Authentic', h['Authentic'].values, c['Authentic'].values, 'Heritage > Contemporary'),
    ('Tone(exp)', 'Tone', h['Tone'].values,     c['Tone'].values,      'Heritage > Contemporary'),
]:
    U, p = mannwhitneyu(g1, g2, alternative='two-sided')
    r = rank_biserial(U, len(g1), len(g2))
    mw_rows.append({
        'Hypothesis':           hyp,
        'DV':                   dv,
        'Predicted_Direction':  direction,
        'Mean_Heritage':        round(h[dv].mean(), 3),
        'Mean_Contemporary':    round(c[dv].mean(), 3),
        'Direction_Correct':    r > 0,
        'U':                    U,
        'p_raw':                round(p, 4),
        'r_rb':                 r,
    })

mw_df = pd.DataFrame(mw_rows)

# Apply Holm-Bonferroni to 4 primary tests
primary = mw_df[mw_df['Hypothesis'] != 'Tone(exp)'].copy().sort_values('p_raw').reset_index(drop=True)
primary['p_holm']    = holm_bonferroni(primary['p_raw'].tolist())
primary['Supported'] = primary['p_holm'] < 0.05

# ── Robustness: AP excluded ───────────────────────────────────────────────
bm_noAP = bm[bm['brand_id'] != 'AudemarsPiguet']
h_na = bm_noAP[bm_noAP['BN'] == 1]
c_na = bm_noAP[bm_noAP['BN'] == 0]

rob_rows = []
for hyp, dv, g1, g2 in [
    ('H1a_noAP', 'Clout',     c_na['Clout'].values,     h_na['Clout'].values),
    ('H1b_noAP', 'money',     c_na['money'].values,     h_na['money'].values),
    ('H2a_noAP', 'Analytic',  h_na['Analytic'].values,  c_na['Analytic'].values),
    ('H2b_noAP', 'Authentic', h_na['Authentic'].values, c_na['Authentic'].values),
]:
    U, p = mannwhitneyu(g1, g2, alternative='two-sided')
    rob_rows.append({'Hypothesis': hyp, 'DV': dv, 'U': U,
                     'p_raw': round(p, 4), 'r_rb': rank_biserial(U, len(g1), len(g2))})
rob_df = pd.DataFrame(rob_rows)

# ── Robustness: Money 2023-2026 ───────────────────────────────────────────
df_rec  = df[df['created_date'] >= '2023-01-01']
bm_rec  = df_rec.groupby(['brand_id', 'brand_nature'])[['money']].mean().reset_index()
h_rec   = bm_rec[bm_rec['brand_nature'] == 'Heritage']['money'].values
c_rec   = bm_rec[bm_rec['brand_nature'] == 'Contemporary']['money'].values
U_rec, p_rec = mannwhitneyu(c_rec, h_rec, alternative='two-sided')
rob_money = pd.DataFrame([{
    'Hypothesis': 'H1b_2023plus', 'DV': 'money', 'n_posts': len(df_rec),
    'U': U_rec, 'p_raw': round(p_rec, 4),
    'r_rb': rank_biserial(U_rec, len(c_rec), len(h_rec))
}])

# ── Robustness: Min-n >= 200 ──────────────────────────────────────────────
eligible = df.groupby('brand_id').size()
eligible = eligible[eligible >= 200].index
bm_minn  = bm[bm['brand_id'].isin(eligible)]
h_mn = bm_minn[bm_minn['BN'] == 1]
c_mn = bm_minn[bm_minn['BN'] == 0]

rob_minn_rows = []
for hyp, dv, g1, g2 in [
    ('H1a_minn', 'Clout',     c_mn['Clout'].values,     h_mn['Clout'].values),
    ('H1b_minn', 'money',     c_mn['money'].values,     h_mn['money'].values),
    ('H2a_minn', 'Analytic',  h_mn['Analytic'].values,  c_mn['Analytic'].values),
    ('H2b_minn', 'Authentic', h_mn['Authentic'].values, c_mn['Authentic'].values),
]:
    U, p = mannwhitneyu(g1, g2, alternative='two-sided')
    rob_minn_rows.append({'Hypothesis': hyp, 'DV': dv, 'U': U,
                          'p_raw': round(p, 4), 'r_rb': rank_biserial(U, len(g1), len(g2))})
rob_minn_df = pd.DataFrame(rob_minn_rows)

print("  Done.")

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 2 — Brand-level OLS regression (n=10)
# ─────────────────────────────────────────────────────────────────────────────

print("Layer 2: Brand-level OLS regression (n=10)...")

l2_rows = []
for dv in DVS_PRIMARY:
    res, vif_bn, vif_price, cooks = run_layer2_ols(dv, bm)
    rm_i  = bm[bm['brand_id'] == 'RichardMille'].index[0] - bm.index[0]
    mbf_i = bm[bm['brand_id'] == 'MBandF'].index[0]      - bm.index[0]
    l2_rows.append({
        'DV':              dv,
        'n':               10,
        'beta_BN':         round(res.params[1], 3),
        'beta_lnPrice':    round(res.params[2], 3),
        'SE_BN_HC2':       round(res.bse[1], 3),
        'SE_lnPrice_HC2':  round(res.bse[2], 3),
        'p_BN':            round(res.pvalues[1], 4),
        'p_lnPrice':       round(res.pvalues[2], 4),
        'R2':              round(res.rsquared, 3),
        'R2_adj':          round(res.rsquared_adj, 3),
        'VIF_BN':          vif_bn,
        'VIF_lnPrice':     vif_price,
        'CooksD_RM':       round(cooks[rm_i], 4),
        'CooksD_MBF':      round(cooks[mbf_i], 4),
    })
l2_df = pd.DataFrame(l2_rows)

# Sensitivity: exclude Richard Mille and MB&F
bm_sens  = bm[~bm['brand_id'].isin(['RichardMille', 'MBandF'])].reset_index(drop=True)
l2s_rows = []
for dv in DVS_PRIMARY:
    res, _, _, _ = run_layer2_ols(dv, bm_sens)
    l2s_rows.append({
        'DV': dv, 'n': 8,
        'beta_BN':      round(res.params[1], 3),
        'beta_lnPrice': round(res.params[2], 3),
        'p_BN':         round(res.pvalues[1], 4),
        'p_lnPrice':    round(res.pvalues[2], 4),
        'R2':           round(res.rsquared, 3),
    })
l2s_df = pd.DataFrame(l2s_rows)

print("  Done.")

# ─────────────────────────────────────────────────────────────────────────────
# LAYER 3 — Post-level OLS regression (n=6,342, descriptive)
# ─────────────────────────────────────────────────────────────────────────────

print("Layer 3: Post-level OLS regression (n=6,342)...")

l3_rows = []
for dv in DVS_PRIMARY:
    sub = df[df[dv].notna()].copy()
    y   = sub[dv].values
    X   = sm.add_constant(sub[['BN', 'ln_price', 'ln_WC']].values)
    res = sm.OLS(y, X).fit(cov_type='HC3')   # HC3 is preferred at large n
    X_pred = sm.add_constant(sub[['BN', 'ln_price', 'ln_WC']].values)
    vif = [round(variance_inflation_factor(X_pred, i), 2) for i in range(1, 4)]
    l3_rows.append({
        'DV':           dv,
        'n':            len(y),
        'beta_BN':      round(res.params[1], 3),
        'beta_lnPrice': round(res.params[2], 3),
        'beta_lnWC':    round(res.params[3], 3),
        'p_BN':         round(res.pvalues[1], 4),
        'p_lnPrice':    round(res.pvalues[2], 4),
        'p_lnWC':       round(res.pvalues[3], 4),
        'R2':           round(res.rsquared, 3),
        'VIF_BN':       vif[0],
        'VIF_lnPrice':  vif[1],
        'VIF_lnWC':     vif[2],
        'Note':         'Descriptive only'
    })
l3_df = pd.DataFrame(l3_rows)

print("  Done.")

# ─────────────────────────────────────────────────────────────────────────────
# AP CONVERGENCE TEST
# ─────────────────────────────────────────────────────────────────────────────

print("AP convergence test...")

ap   = bm[bm['brand_id'] == 'AudemarsPiguet'].iloc[0]
h5   = bm[bm['BN'] == 1]                                       # all 5 Heritage brands
c4   = bm[(bm['BN'] == 0) & (bm['brand_id'] != 'AudemarsPiguet')]  # 4 Contemporary excl. AP

ap_rows = []
convergence = {'Heritage': 0, 'Contemporary': 0}
for dv in DVS_PRIMARY:
    pooled_sd = (h5[dv].std() + c4[dv].std()) / 2
    z_h = abs(ap[dv] - h5[dv].mean()) / pooled_sd
    z_c = abs(ap[dv] - c4[dv].mean()) / pooled_sd
    closer = 'Heritage' if z_h < z_c else 'Contemporary'
    convergence[closer] += 1
    ap_rows.append({
        'DV':                 dv,
        'AP_mean':            round(ap[dv], 3),
        'Heritage_group_mean':round(h5[dv].mean(), 3),
        'Contemp_group_mean': round(c4[dv].mean(), 3),
        'z_dist_Heritage':    round(z_h, 3),
        'z_dist_Contemporary':round(z_c, 3),
        'Closer_to':          closer,
    })

ap_df = pd.DataFrame(ap_rows)
ap_verdict = 'Contemporary' if convergence['Contemporary'] >= 3 else \
             'Heritage'     if convergence['Heritage']     >= 3 else 'Mixed'

print(f"  AP converges with: {ap_verdict} ({convergence['Heritage']}/4 Heritage, "
      f"{convergence['Contemporary']}/4 Contemporary)")
print("  Done.")

# ─────────────────────────────────────────────────────────────────────────────
# EXPORT TO EXCEL
# ─────────────────────────────────────────────────────────────────────────────

print(f"\nWriting results to {OUTPUT_XLS} ...")

brand_export = bm[['brand_id', 'brand_nature', 'n_posts', 'price_eur', 'entry_model']
                  + DVS_ALL].copy().round(3)
brand_export.columns = ['Brand', 'Nature', 'N_posts', 'Price_EUR', 'Entry_Model',
                        'Analytic', 'Clout', 'Authentic', 'money', 'Tone']

with pd.ExcelWriter(OUTPUT_XLS, engine='openpyxl') as writer:
    brand_export.to_excel(         writer, sheet_name='Brand_Means',               index=False)
    primary.to_excel(              writer, sheet_name='Layer1_MannWhitney',         index=False)
    mw_df[mw_df['Hypothesis']=='Tone(exp)'].to_excel(
                                   writer, sheet_name='Layer1_Tone_Exploratory',    index=False)
    rob_df.to_excel(               writer, sheet_name='Layer1_Robustness_noAP',     index=False)
    rob_money.to_excel(            writer, sheet_name='Layer1_Robustness_Money2023',index=False)
    rob_minn_df.to_excel(          writer, sheet_name='Layer1_Robustness_minn200',  index=False)
    l2_df.to_excel(                writer, sheet_name='Layer2_OLS_brandlevel',      index=False)
    l2s_df.to_excel(               writer, sheet_name='Layer2_Sensitivity_noRMnMBF',index=False)
    l3_df.to_excel(                writer, sheet_name='Layer3_OLS_postlevel',       index=False)
    ap_df.to_excel(                writer, sheet_name='AP_Convergence',             index=False)
    df[['item_id', 'brand_id', 'brand_nature', 'created_date', 'WC', 'ln_WC',
        'price_eur', 'ln_price', 'BN', 'Analytic', 'Clout', 'Authentic',
        'money', 'Tone']].to_excel(writer, sheet_name='Raw_PostLevel',             index=False)

print("Done! Results written to thesis_analysis_v2.xlsx")
print("\nSummary of key findings:")
print(f"  Layer 1 primary: {primary[['Hypothesis','DV','p_raw','p_holm','r_rb','Supported']].to_string(index=False)}")
print(f"\n  Layer 2 Authentic (key result): beta_BN={l2_df[l2_df['DV']=='Authentic']['beta_BN'].values[0]}, "
      f"p={l2_df[l2_df['DV']=='Authentic']['p_BN'].values[0]}")
print(f"  AP classification validated: converges with {ap_verdict} on {convergence[ap_verdict]}/4 DVs")
