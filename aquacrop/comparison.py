__all__ = ["run_comparison"]

# Cell
import sys

_ = [sys.path.append(i) for i in [".", ".."]]

# Cell
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from .core import *
from .classes import *
import seaborn as sns

# Cell
def run_comparison(model, name):
    """
    Function to run a comparison between python matlab and windows.
    Plots yields and prints mean and mean absolute error between them

    *Arguments:*


    `name`: `str` : name of directory containing input files

    *Returns:*

    None


    """
    Outputs = model.Outputs

    py = Outputs.Final.round(3)
    py.columns = [
        "Season",
        "CropType",
        "HarvestDate",
        "Harvest Date (Step)",
        "Yield",
        "Seasonal irrigation (mm)",
    ]

    matlab = pd.read_csv(get_filepath(name + "_matlab.txt"), delim_whitespace=True, header=None)
    matlab.columns = [
        "season",
        "crop",
        "plantdate",
        "stepplant",
        "harvestdate",
        "stepharvest",
        "Yield",
        "tirr",
    ]

    windows_names = "    RunNr     Day1   Month1    Year1     Rain      ETo       GD     CO2      Irri   Infilt   Runoff    Drain   Upflow        E     E/Ex       Tr      TrW   Tr/Trx    SaltIn   SaltOut    SaltUp  SaltProf     Cycle   SaltStr  FertStr  WeedStr  TempStr   ExpStr   StoStr  BioMass  Brelative   HI     Yield     WPet     DayN   MonthN    YearN".split()
    windows = pd.read_csv(
        get_filepath(name + "_windows.OUT"), skiprows=5, delim_whitespace=True, names=windows_names
    )

    combined = pd.DataFrame([py.Yield, windows.Yield, matlab.Yield]).T

    combined.columns = ["py", "windows", "matlab"]
    mae = np.round(np.abs(combined.py - combined.windows).mean(), 2)
    pymean = combined.mean().py.round(2)
    print(f"python seasonal mean: {pymean} kg/ha\nMAE from windows: {mae} kg/ha")

    mae_mat = np.round(np.abs(combined.py - combined.matlab).mean(), 3)
    print(f"MAE from matlab:  {mae_mat} kg/ha")

    plt.style.use("seaborn")

    fig, ax = plt.subplots(2, 1, sharex=True, figsize=(11, 8))

    ax[0].plot(py.Yield, label="Python")
    ax[0].plot(matlab.Yield, label="Matlab")
    ax[0].plot(windows.Yield, "--", label="Windows")
    ax[0].legend(fontsize=18)
    ax[0].set_ylabel("Yield", fontsize=18)

    # sns.jointplot(np.arange(len(py)), py.Yield - windows.Yield,
    #            kind="resid",color="m",ratio=10)

    ax[1].scatter(np.arange(len(py)), py.Yield - windows.Yield, label="Python")
    ax[1].scatter(np.arange(len(py)), matlab.Yield - windows.Yield, label="Matlab")
    ax[1].plot([0, len(py)], [0, 0], "--", color="black")
    ax[1].set_xlabel("Season", fontsize=18)
    ax[1].set_ylabel("Residuals", fontsize=18)
    ax[1].legend(fontsize=18)

    plt.show()

    return Outputs, windows
