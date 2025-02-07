__all__ = ["solution", "check_model_termination", "reset_initial_conditions", "update_time"]

# Cell
from .solution import *
from .initialize import calculate_HI_linear, calculate_HIGC
from .classes import *
import numpy as np
import pandas as pd




# compiled functions
from .solution_aot import (
    _growing_degree_day, 
    _drainage, 
    _root_zone_water, 
    _rainfall_partition, 
    _check_groundwater_table, 
    _soil_evaporation,
    _root_development, 
    _infiltration, 
    _HIref_current_day, 
    _biomass_accumulation)


# Cell
def solution(InitCond, ParamStruct, ClockStruct, weather_step, Outputs):
    """
    Function to perform AquaCrop-OS solution for a single time step



    *Arguments:*\n

    `InitCond` : `InitCondClass` :  containing current model paramaters

    `ClockStruct` : `ClockStructClass` :  model time paramaters

    `weather_step`: `np.array` :  containing P,ET,Tmax,Tmin for current day

    `Outputs` : `OutputClass` :  object to store outputs

    *Returns:*

    `NewCond` : `InitCondClass` :  containing updated model paramaters

    `Outputs` : `OutputClass` :  object to store outputs



    """

    # Unpack structures
    Soil = ParamStruct.Soil
    CO2 = ParamStruct.CO2
    if ParamStruct.WaterTable == 1:
        Groundwater = ParamStruct.zGW[ClockStruct.TimeStepCounter]
    else:
        Groundwater = 0

    P = weather_step[2]
    Tmax = weather_step[1]
    Tmin = weather_step[0]
    Et0 = weather_step[3]

    # Store initial conditions in structure for updating %%
    NewCond = InitCond

    # Check if growing season is active on current time step %%
    if ClockStruct.SeasonCounter >= 0:
        # Check if in growing season
        CurrentDate = ClockStruct.StepStartTime
        PlantingDate = ClockStruct.PlantingDates[ClockStruct.SeasonCounter]
        HarvestDate = ClockStruct.HarvestDates[ClockStruct.SeasonCounter]

        if (
            (PlantingDate <= CurrentDate)
            and (HarvestDate >= CurrentDate)
            and (NewCond.CropMature == False)
            and (NewCond.CropDead == False)
        ):
            GrowingSeason = True
        else:
            GrowingSeason = False

        # Assign crop, irrigation management, and field management structures
        Crop_ = ParamStruct.Seasonal_Crop_List[ClockStruct.SeasonCounter]
        Crop_Name = ParamStruct.CropChoices[ClockStruct.SeasonCounter]
        IrrMngt = ParamStruct.IrrMngt

        if GrowingSeason == True:
            FieldMngt = ParamStruct.FieldMngt
        else:
            FieldMngt = ParamStruct.FallowFieldMngt

    else:
        # Not yet reached start of first growing season
        GrowingSeason = False
        # Assign crop, irrigation management, and field management structures
        # Assign first crop as filler crop
        Crop_ = ParamStruct.Fallow_Crop
        Crop_Name = "fallow"

        Crop_.Aer = 5
        Crop_.Zmin = 0.3
        IrrMngt = ParamStruct.FallowIrrMngt
        FieldMngt = ParamStruct.FallowFieldMngt


    

    # Increment time counters %%
    if GrowingSeason == True:
        # Calendar days after planting
        NewCond.DAP = NewCond.DAP + 1
        # Growing degree days after planting

        GDD = _growing_degree_day(Crop_.GDDmethod, Crop_.Tupp, Crop_.Tbase, Tmax, Tmin)

        ## Update cumulative GDD counter ##
        NewCond.GDD = GDD
        NewCond.GDDcum = NewCond.GDDcum + GDD

        NewCond.GrowingSeason = True
    else:
        NewCond.GrowingSeason = False

        # Calendar days after planting
        NewCond.DAP = 0
        # Growing degree days after planting
        GDD = 0.3
        NewCond.GDDcum = 0

    # save current timestep counter
    NewCond.TimeStepCounter = ClockStruct.TimeStepCounter
    NewCond.P = weather_step[2]
    NewCond.Tmax = weather_step[1]
    NewCond.Tmin = weather_step[0]
    NewCond.Et0 = weather_step[3]


    

    class_args = {key:value for key, value in Crop_.__dict__.items() if not key.startswith('__') and not callable(key)}
    Crop = CropStructNT(**class_args)



    # Run simulations %%
    # 1. Check for groundwater table
    (
        NewCond.th_fc_Adj,
        _
    ) = _check_groundwater_table(
        Soil.Profile,
        NewCond.zGW,
        NewCond.th,
        NewCond.th_fc_Adj,
        ParamStruct.WaterTable,
        Groundwater,
    )

    # 2. Root development
    NewCond.Zroot = _root_development(
        Crop,
        Soil.Profile,
        NewCond.DAP,
        NewCond.Zroot,
        NewCond.DelayedCDs,
        NewCond.GDDcum,
        NewCond.DelayedGDDs,
        NewCond.TrRatio,
        NewCond.th,
        NewCond.CC,
        NewCond.CC_NS,
        NewCond.Germination,
        NewCond.rCor,
        NewCond.Tpot,
        NewCond.zGW,
        GDD,
        GrowingSeason,
        ParamStruct.WaterTable
    )

    # 3. Pre-irrigation
    NewCond, PreIrr = pre_irrigation(Soil.Profile, Crop, NewCond, GrowingSeason, IrrMngt)

    # 4. Drainage

    NewCond.th, DeepPerc, FluxOut = _drainage(
        Soil.Profile,
        NewCond.th,
        NewCond.th_fc_Adj,
    )

    # 5. Surface runoff
    Runoff, Infl, NewCond.DaySubmerged = _rainfall_partition(
        P,
        NewCond.th,
        NewCond.DaySubmerged,
        FieldMngt.SRinhb,
        FieldMngt.Bunds,
        FieldMngt.zBund,
        FieldMngt.CNadjPct,
        Soil.CN,
        Soil.AdjCN,
        Soil.zCN,
        Soil.nComp,
        Soil.Profile,
    )

    # 6. Irrigation
    NewCond.Depletion,NewCond.TAW,NewCond.IrrCum, Irr = irrigation(

        IrrMngt.IrrMethod,
        IrrMngt.SMT,
        IrrMngt.AppEff,
        IrrMngt.MaxIrr,
        IrrMngt.IrrInterval,
        IrrMngt.Schedule,
        IrrMngt.depth,
        IrrMngt.MaxIrrSeason,
        NewCond.GrowthStage,
        NewCond.IrrCum,
        NewCond.Epot,
        NewCond.Tpot,
        NewCond.Zroot,
        NewCond.th,
        NewCond.DAP,
        NewCond.TimeStepCounter, Crop, Soil.Profile, Soil.zTop, GrowingSeason, P, Runoff
    )

    # 7. Infiltration
    NewCond.th,NewCond.SurfaceStorage, DeepPerc, RunoffTot, Infl, FluxOut = _infiltration(
        Soil.Profile,
        NewCond.SurfaceStorage, 
        NewCond.th_fc_Adj, 
        NewCond.th,
        Infl,
        Irr,
        IrrMngt.AppEff,
        FieldMngt.Bunds,
        FieldMngt.zBund,
        FluxOut,
        DeepPerc,
        Runoff,
        GrowingSeason,
    )
    # 8. Capillary Rise
    NewCond, CR = capillary_rise(
        Soil.Profile, Soil.nLayer, Soil.fshape_cr, NewCond, FluxOut, ParamStruct.WaterTable
    )

    # 9. Check germination
    NewCond = germination(
        NewCond, Soil.zGerm, Soil.Profile, Crop.GermThr, Crop.PlantMethod, GDD, GrowingSeason
    )

    # 10. Update growth stage
    NewCond = growth_stage(Crop, NewCond, GrowingSeason)

    # 11. Canopy cover development
    NewCond = canopy_cover(Crop, Soil.Profile, Soil.zTop, NewCond, GDD, Et0, GrowingSeason)

    # 12. Soil evaporation
    NewCond.Epot,NewCond.th,NewCond.Stage2,NewCond.Wstage2,NewCond.Wsurf,NewCond.SurfaceStorage,NewCond.EvapZ, Es, EsPot = _soil_evaporation(
        ClockStruct.EvapTimeSteps,
        ClockStruct.SimOffSeason,
        ClockStruct.TimeStepCounter,
        Soil.Profile,
        Soil.EvapZmin,
        Soil.EvapZmax,
        Soil.REW,
        Soil.Kex,
        Soil.fwcc,
        Soil.fWrelExp,
        Soil.fevap,
        Crop.CalendarType,
        Crop.Senescence,
        IrrMngt.IrrMethod,
        IrrMngt.WetSurf,
        FieldMngt.Mulches,
        FieldMngt.fMulch,
        FieldMngt.MulchPct,
        NewCond.DAP,
        NewCond.Wsurf,
        NewCond.EvapZ,
        NewCond.Stage2,
        NewCond.th,
        NewCond.DelayedCDs,
        NewCond.GDDcum,
        NewCond.DelayedGDDs,
        NewCond.CCxW,
        NewCond.CCadj,
        NewCond.CCxAct,
        NewCond.CC,
        NewCond.PrematSenes,
        NewCond.SurfaceStorage,
        NewCond.Wstage2,
        NewCond.Epot,
        Et0,
        Infl,
        P,
        Irr,
        GrowingSeason,
    )

    # 13. Crop transpiration
    Tr, TrPot_NS, TrPot, NewCond, IrrNet = transpiration(
        Soil.Profile,
        Soil.nComp,
        Soil.zTop,
        Crop,
        IrrMngt.IrrMethod,
        IrrMngt.NetIrrSMT,
        NewCond,
        Et0,
        CO2,
        GrowingSeason,
        GDD,
    )

    # 14. Groundwater inflow
    NewCond, GwIn = groundwater_inflow(Soil.Profile, NewCond)

    # 15. Reference harvest index
    (NewCond.HIref,
    NewCond.YieldForm,
    NewCond.PctLagPhase,
    ) = _HIref_current_day(NewCond.HIref,
                        NewCond.DAP,
                        NewCond.DelayedCDs,
                        NewCond.YieldForm,
                        NewCond.PctLagPhase,
                        NewCond.CCprev,
                        Crop,
                        GrowingSeason)

    # 16. Biomass accumulation
    (NewCond.B, NewCond.B_NS) = _biomass_accumulation(Crop,
                            NewCond.DAP,
                            NewCond.DelayedCDs,
                            NewCond.HIref,
                            NewCond.PctLagPhase,
                            NewCond.B,
                            NewCond.B_NS,
                            Tr, 
                            TrPot_NS, 
                            Et0, 
                            GrowingSeason)

    # 17. Harvest index
    NewCond = harvest_index(Soil.Profile, Soil.zTop, Crop, NewCond, Et0, Tmax, Tmin, GrowingSeason)

    # 18. Crop yield
    if GrowingSeason == True:
        # Calculate crop yield (tonne/ha)
        NewCond.Y = (NewCond.B / 100) * NewCond.HIadj
        # print( ClockStruct.TimeStepCounter,(NewCond.B/100),NewCond.HIadj)
        # Check if crop has reached maturity
        if ((Crop.CalendarType == 1) and (NewCond.DAP >= Crop.Maturity)) or (
            (Crop.CalendarType == 2) and (NewCond.GDDcum >= Crop.Maturity)
        ):
            # Crop has reached maturity
            NewCond.CropMature = True

    elif GrowingSeason == False:
        # Crop yield is zero outside of growing season
        NewCond.Y = 0

    # 19. Root zone water
    _TAW = TAWClass()
    _Dr = DrClass()
    # thRZ = thRZClass()

    Wr, _Dr.Zt, _Dr.Rz, _TAW.Zt, _TAW.Rz, _, _, _, _, _, _ = _root_zone_water(
        Soil.Profile,
        float(NewCond.Zroot),
        NewCond.th,
        Soil.zTop,
        float(Crop.Zmin),
        Crop.Aer,
    )

    # Wr, _Dr, _TAW, _thRZ = root_zone_water(
    #     Soil.Profile, NewCond.Zroot, NewCond.th, Soil.zTop, float(Crop.Zmin), Crop.Aer
    # )

    # 20. Update net irrigation to add any pre irrigation
    IrrNet = IrrNet + PreIrr
    NewCond.IrrNetCum = NewCond.IrrNetCum + PreIrr

    # Update model outputs %%
    row_day = ClockStruct.TimeStepCounter
    row_gs = ClockStruct.SeasonCounter

    # Irrigation
    if GrowingSeason == True:
        if IrrMngt.IrrMethod == 4:
            # Net irrigation
            IrrDay = IrrNet
            IrrTot = NewCond.IrrNetCum
        else:
            # Irrigation
            IrrDay = Irr
            IrrTot = NewCond.IrrCum

    else:
        IrrDay = 0
        IrrTot = 0

        NewCond.Depletion = _Dr.Rz
        NewCond.TAW = _TAW.Rz

    # Water contents
    Outputs.Water[row_day, :3] = np.array([ClockStruct.TimeStepCounter, GrowingSeason, NewCond.DAP])
    Outputs.Water[row_day, 3:] = NewCond.th

    # Water fluxes
    Outputs.Flux[row_day, :] = [
        ClockStruct.TimeStepCounter,
        ClockStruct.SeasonCounter,
        NewCond.DAP,
        Wr,
        NewCond.zGW,
        NewCond.SurfaceStorage,
        IrrDay,
        Infl,
        Runoff,
        DeepPerc,
        CR,
        GwIn,
        Es,
        EsPot,
        Tr,
        P,
    ]

    # Crop growth
    Outputs.Growth[row_day, :] = [
        ClockStruct.TimeStepCounter,
        ClockStruct.SeasonCounter,
        NewCond.DAP,
        GDD,
        NewCond.GDDcum,
        NewCond.Zroot,
        NewCond.CC,
        NewCond.CC_NS,
        NewCond.B,
        NewCond.B_NS,
        NewCond.HI,
        NewCond.HIadj,
        NewCond.Y,
    ]

    # Final output (if at end of growing season)
    if ClockStruct.SeasonCounter > -1:
        if (
            (NewCond.CropMature == True)
            or (NewCond.CropDead == True)
            or (ClockStruct.HarvestDates[ClockStruct.SeasonCounter] == ClockStruct.StepEndTime)
        ) and (NewCond.HarvestFlag == False):

            # Store final outputs
            Outputs.Final.loc[ClockStruct.SeasonCounter] = [
                ClockStruct.SeasonCounter,
                Crop_Name,
                ClockStruct.StepEndTime,
                ClockStruct.TimeStepCounter,
                NewCond.Y,
                IrrTot,
            ]

            # Set harvest flag
            NewCond.HarvestFlag = True

    return NewCond, ParamStruct, Outputs


# Cell
def check_model_termination(ClockStruct, InitCond):
    """
    Function to check and declare model termination


    *Arguments:*\n

    `ClockStruct` : `ClockStructClass` :  model time paramaters

    `InitCond` : `InitCondClass` :  containing current model paramaters

    *Returns:*

    `ClockStruct` : `ClockStructClass` : updated clock paramaters


    """

    ## Check if current time-step is the last
    CurrentTime = ClockStruct.StepEndTime
    if CurrentTime < ClockStruct.SimulationEndDate:
        ClockStruct.ModelTermination = False
    elif CurrentTime >= ClockStruct.SimulationEndDate:
        ClockStruct.ModelTermination = True

    ## Check if at the end of last growing season ##
    # Allow model to exit early if crop has reached maturity or died, and in
    # the last simulated growing season
    if (InitCond.HarvestFlag == True) and (ClockStruct.SeasonCounter == ClockStruct.nSeasons - 1):

        ClockStruct.ModelTermination = True

    return ClockStruct


# Cell
def reset_initial_conditions(ClockStruct, InitCond, ParamStruct, weather):

    """
    Function to reset initial model conditions for start of growing
    season (when running model over multiple seasons)

    *Arguments:*\n

    `ClockStruct` : `ClockStructClass` :  model time paramaters

    `InitCond` : `InitCondClass` :  containing current model paramaters

    `weather`: `np.array` :  weather data for simulation period


    *Returns:*

    `InitCond` : `InitCondClass` :  containing reset model paramaters



    """

    ## Extract crop type ##
    CropType = ParamStruct.CropChoices[ClockStruct.SeasonCounter]

    ## Extract structures for updating ##
    Soil = ParamStruct.Soil
    Crop = ParamStruct.Seasonal_Crop_List[ClockStruct.SeasonCounter]
    FieldMngt = ParamStruct.FieldMngt
    CO2 = ParamStruct.CO2
    CO2_data = ParamStruct.CO2data

    ## Reset counters ##
    InitCond.AgeDays = 0
    InitCond.AgeDays_NS = 0
    InitCond.AerDays = 0
    InitCond.IrrCum = 0
    InitCond.DelayedGDDs = 0
    InitCond.DelayedCDs = 0
    InitCond.PctLagPhase = 0
    InitCond.tEarlySen = 0
    InitCond.GDDcum = 0
    InitCond.DaySubmerged = 0
    InitCond.IrrNetCum = 0
    InitCond.DAP = 0

    InitCond.AerDaysComp = np.zeros(int(Soil.nComp))

    ## Reset states ##
    # States
    InitCond.PreAdj = False
    InitCond.CropMature = False
    InitCond.CropDead = False
    InitCond.Germination = False
    InitCond.PrematSenes = False
    InitCond.HarvestFlag = False

    # Harvest index
    # HI
    InitCond.Stage = 1
    InitCond.Fpre = 1
    InitCond.Fpost = 1
    InitCond.fpost_dwn = 1
    InitCond.fpost_upp = 1

    InitCond.HIcor_Asum = 0
    InitCond.HIcor_Bsum = 0
    InitCond.Fpol = 0
    InitCond.sCor1 = 0
    InitCond.sCor2 = 0

    # Growth stage
    InitCond.GrowthStage = 0

    # Transpiration
    InitCond.TrRatio = 1

    # crop growth
    InitCond.rCor = 1

    InitCond.CC = 0
    InitCond.CCadj = 0
    InitCond.CC_NS = 0
    InitCond.CCadj_NS = 0
    InitCond.B = 0
    InitCond.B_NS = 0
    InitCond.HI = 0
    InitCond.HIadj = 0
    InitCond.CCxAct = 0
    InitCond.CCxAct_NS = 0
    InitCond.CCxW = 0
    InitCond.CCxW_NS = 0
    InitCond.CCxEarlySen = 0
    InitCond.CCprev = 0
    InitCond.ProtectedSeed = 0

    ## Update CO2 concentration ##
    # Get CO2 concentration

    if ParamStruct.CO2concAdj != None:
        CO2.CurrentConc = ParamStruct.CO2concAdj
    else:
        Yri = pd.DatetimeIndex([ClockStruct.StepStartTime]).year[0]
        CO2.CurrentConc = CO2_data.loc[Yri]
    # Get CO2 weighting factor for first year
    CO2conc = CO2.CurrentConc
    CO2ref = CO2.RefConc
    if CO2conc <= CO2ref:
        fw = 0
    else:
        if CO2conc >= 550:
            fw = 1
        else:
            fw = 1 - ((550 - CO2conc) / (550 - CO2ref))

    # Determine initial adjustment
    fCO2 = (CO2conc / CO2ref) / (
        1
        + (CO2conc - CO2ref)
        * (
            (1 - fw) * Crop.bsted
            + fw * ((Crop.bsted * Crop.fsink) + (Crop.bface * (1 - Crop.fsink)))
        )
    )

    # Consider crop type
    if Crop.WP >= 40:
        # No correction for C4 crops
        ftype = 0
    elif Crop.WP <= 20:
        # Full correction for C3 crops
        ftype = 1
    else:
        ftype = (40 - Crop.WP) / (40 - 20)

    # Total adjustment
    Crop.fCO2 = 1 + ftype * (fCO2 - 1)

    ## Reset soil water conditions (if not running off-season) ##
    if ClockStruct.SimOffSeason == False:
        # Reset water content to starting conditions
        InitCond.th = InitCond.thini
        # Reset surface storage
        if (FieldMngt.Bunds) and (FieldMngt.zBund > 0.001):
            # Get initial storage between surface bunds
            InitCond.SurfaceStorage = min(FieldMngt.BundWater, FieldMngt.zBund)
        else:
            # No surface bunds
            InitCond.SurfaceStorage = 0

    ## Update crop parameters (if in GDD mode) ##
    if Crop.CalendarType == 2:
        # Extract weather data for upcoming growing season
        wdf = weather[weather[:, 4] >= ClockStruct.PlantingDates[ClockStruct.SeasonCounter]]
        # wdf = wdf[wdf[:,4]<=ClockStruct.HarvestDates[ClockStruct.SeasonCounter]]
        Tmin = wdf[:, 0]
        Tmax = wdf[:, 1]

        # Calculate GDD's
        if Crop.GDDmethod == 1:
            Tmean = (Tmax + Tmin) / 2
            Tmean[Tmean > Crop.Tupp] = Crop.Tupp
            Tmean[Tmean < Crop.Tbase] = Crop.Tbase
            GDD = Tmean - Crop.Tbase
        elif Crop.GDDmethod == 2:
            Tmax[Tmax > Crop.Tupp] = Crop.Tupp
            Tmax[Tmax < Crop.Tbase] = Crop.Tbase
            Tmin[Tmin > Crop.Tupp] = Crop.Tupp
            Tmin[Tmin < Crop.Tbase] = Crop.Tbase
            Tmean = (Tmax + Tmin) / 2
            GDD = Tmean - Crop.Tbase
        elif Crop.GDDmethod == 3:
            Tmax[Tmax > Crop.Tupp] = Crop.Tupp
            Tmax[Tmax < Crop.Tbase] = Crop.Tbase
            Tmin[Tmin > Crop.Tupp] = Crop.Tupp
            Tmean = (Tmax + Tmin) / 2
            Tmean[Tmean < Crop.Tbase] = Crop.Tbase
            GDD = Tmean - Crop.Tbase

        GDDcum = np.cumsum(GDD)

        assert (
            GDDcum[-1] > Crop.Maturity
        ), f"not enough growing degree days in simulation ({GDDcum[-1]}) to reach maturity ({Crop.Maturity})"

        Crop.MaturityCD = np.argmax((GDDcum > Crop.Maturity)) + 1

        assert Crop.MaturityCD < 365, "crop will take longer than 1 year to mature"

        # 1. GDD's from sowing to maximum canopy cover
        Crop.MaxCanopyCD = (GDDcum > Crop.MaxCanopy).argmax() + 1
        # 2. GDD's from sowing to end of vegetative growth
        Crop.CanopyDevEndCD = (GDDcum > Crop.CanopyDevEnd).argmax() + 1
        # 3. Calendar days from sowing to start of yield formation
        Crop.HIstartCD = (GDDcum > Crop.HIstart).argmax() + 1
        # 4. Calendar days from sowing to end of yield formation
        Crop.HIendCD = (GDDcum > Crop.HIend).argmax() + 1
        # 5. Duration of yield formation in calendar days
        Crop.YldFormCD = Crop.HIendCD - Crop.HIstartCD
        if Crop.CropType == 3:
            # 1. Calendar days from sowing to end of flowering
            FloweringEnd = (GDDcum > Crop.FloweringEnd).argmax() + 1
            # 2. Duration of flowering in calendar days
            Crop.FloweringCD = FloweringEnd - Crop.HIstartCD
        else:
            Crop.FloweringCD = -999

        # Update harvest index growth coefficient
        Crop = calculate_HIGC(Crop)

        # Update day to switch to linear HI build-up
        if Crop.CropType == 3:
            # Determine linear switch point and HIGC rate for fruit/grain crops
            Crop = calculate_HI_linear(Crop)

        else:
            # No linear switch for leafy vegetable or root/tiber crops
            Crop.tLinSwitch = 0
            Crop.dHILinear = 0.0

    ## Update global variables ##
    ParamStruct.Seasonal_Crop_List[ClockStruct.SeasonCounter] = Crop
    ParamStruct.CO2 = CO2

    return InitCond, ParamStruct


# Cell
def update_time(ClockStruct, InitCond, ParamStruct, Outputs, weather):
    """
    Function to update current time in model

    *Arguments:*\n

    `ClockStruct` : `ClockStructClass` :  model time paramaters

    `InitCond` : `InitCondClass` :  containing current model paramaters

    `weather`: `np.array` :  weather data for simulation period


    *Returns:*

    `ClockStruct` : `ClockStructClass` :  model time paramaters


    `InitCond` : `InitCondClass` :  containing reset model paramaters


    """
    ## Update time ##
    if ClockStruct.ModelTermination == False:
        if (InitCond.HarvestFlag == True) and ((ClockStruct.SimOffSeason == False)):
            # End of growing season has been reached and not simulating
            # off-season soil water balance. Advance time to the start of the
            # next growing season.
            # Check if in last growing season
            if ClockStruct.SeasonCounter < ClockStruct.nSeasons - 1:
                # Update growing season counter
                ClockStruct.SeasonCounter = ClockStruct.SeasonCounter + 1
                # Update time-step counter
                # ClockStruct.TimeSpan = pd.Series(ClockStruct.TimeSpan)
                ClockStruct.TimeStepCounter = ClockStruct.TimeSpan.get_loc(
                    ClockStruct.PlantingDates[ClockStruct.SeasonCounter]
                )
                # Update start time of time-step
                ClockStruct.StepStartTime = ClockStruct.TimeSpan[ClockStruct.TimeStepCounter]
                # Update end time of time-step
                ClockStruct.StepEndTime = ClockStruct.TimeSpan[ClockStruct.TimeStepCounter + 1]
                # Reset initial conditions for start of growing season
                InitCond, ParamStruct = reset_initial_conditions(
                    ClockStruct, InitCond, ParamStruct, weather
                )

        else:
            # Simulation considers off-season, so progress by one time-step
            # (one day)
            # Time-step counter
            ClockStruct.TimeStepCounter = ClockStruct.TimeStepCounter + 1
            # Start of time step (beginning of current day)
            # ClockStruct.TimeSpan = pd.Series(ClockStruct.TimeSpan)
            ClockStruct.StepStartTime = ClockStruct.TimeSpan[ClockStruct.TimeStepCounter]
            # End of time step (beginning of next day)
            ClockStruct.StepEndTime = ClockStruct.TimeSpan[ClockStruct.TimeStepCounter + 1]
            # Check if in last growing season
            if ClockStruct.SeasonCounter < ClockStruct.nSeasons - 1:
                # Check if upcoming day is the start of a new growing season
                if (
                    ClockStruct.StepStartTime
                    == ClockStruct.PlantingDates[ClockStruct.SeasonCounter + 1]
                ):
                    # Update growing season counter
                    ClockStruct.SeasonCounter = ClockStruct.SeasonCounter + 1
                    # Reset initial conditions for start of growing season
                    InitCond, ParamStruct = reset_initial_conditions(
                        ClockStruct, InitCond, ParamStruct, weather
                    )

    elif ClockStruct.ModelTermination == True:
        ClockStruct.StepStartTime = ClockStruct.StepEndTime
        ClockStruct.StepEndTime = ClockStruct.StepEndTime + np.timedelta64(1, "D")

        Outputs.Flux = pd.DataFrame(
            Outputs.Flux,
            columns=[
                "TimeStepCounter",
                "SeasonCounter",
                "DAP",
                "Wr",
                "zGW",
                "SurfaceStorage",
                "IrrDay",
                "Infl",
                "Runoff",
                "DeepPerc",
                "CR",
                "GwIn",
                "Es",
                "EsPot",
                "Tr",
                "P",
            ],
        )

        Outputs.Water = pd.DataFrame(
            Outputs.Water,
            columns=["TimeStepCounter", "GrowingSeason", "DAP"]
            + ["th" + str(i) for i in range(1, Outputs.Water.shape[1] - 2)],
        )

        Outputs.Growth = pd.DataFrame(
            Outputs.Growth,
            columns=[
                "TimeStepCounter",
                "SeasonCounter",
                "DAP",
                "GDD",
                "GDDcum",
                "Zroot",
                "CC",
                "CC_NS",
                "B",
                "B_NS",
                "HI",
                "HIadj",
                "Y",
            ],
        )

    return ClockStruct, InitCond, ParamStruct, Outputs
