import matplotlib.pyplot as plt
import seaborn as sns

def apply_theme():
    sns.set_theme(style="whitegrid", palette="deep")
    plt.rcParams.update({
        "figure.figsize":   (12, 5),
        "figure.dpi":       110,
        "axes.titleweight": "bold",
        "axes.titlesize":   13,
        "axes.labelsize":   11,
        "font.size":        10,
        "axes.spines.top":  False,   
        "axes.spines.right": False,
        "grid.alpha":       0.4,
    })
