import numpy as np
import multiprocessing as mp
import time, os
import numpy.linalg as LA
import subprocess as sp
from random import random

import Model_Miller_3 as model


def getGlobalParams():
    global dtE, dtI, NSteps, NTraj, NStates, M, windowtype
    global adjustedgamma, NCPUS, initstate, dirName, NSkip
    dtE = model.parameters.dtE
    dtI = model.parameters.dtI
    NSteps = model.parameters.NSteps
    NTraj = model.parameters.NTraj
    NStates = model.parameters.NStates
    M = model.parameters.M
    windowtype = model.parameters.windowtype.lower()
    adjustedgamma = model.parameters.adjustedgamma.lower()
    NCPUS = model.parameters.NCPUS
    initstate = model.parameters.initState
    dirName = model.parameters.dirName
    NSkip = model.parameters.NSkip


def initFiles(traj):
    name = f"{dirName}/traj-{traj}/"
    sp.call(f"mkdir -p {name}", shell=True)
    #sp.call(f"rm {name}/*dat", shell=True)

    InitCondsFile = open(f"{name}/initConds.dat","w")
    densityFile = open(f"{name}/density.dat","w")
    mappingFile = open(f"{name}/mapping.dat","w")
    return InitCondsFile,densityFile, mappingFile

def closeFiles(InitCondsFile, densityFile, mappingFile):
    InitCondsFile.close()
    densityFile.close()
    mappingFile.close()


def initMapping(InitCondsFile):
    """
    Initialize mapping variables according to various SQC schemes
    """

    # Initialize mapping variables
    ek = np.zeros((NStates))
    angle = np.zeros((NStates))

    if (windowtype == "square"):
        for i in range(NStates):
            ek[i] = 2*0.366*random()
            angle[i] = random() * 2 * np.pi
        
    elif (windowtype == "triangle"):
        # Initial state
        while (True):
            ek[initstate] = random()
            if ( 1 - ek[initstate] >= random() ):
                break
        
        # Other states
        for i in range(NStates):
            angle[i] = random() * 2 * np.pi
            if (i != initstate):
                rand = random() * ( 1 - ek[initstate] )
                ek[i] = rand
        
    # Shift up initial state
    ek[initstate] += 1


    ### Now we assign mapping oscillator initial conditions ###   
    z = np.zeros((NStates), dtype=complex)
    ZPE = np.zeros((NStates))

    for state in range(NStates):
        # Construct zero-point energy (ZPE)
        if (adjustedgamma == "no"):    
            ZPE[state] = (np.sqrt(3)-1)/2 * (windowtype == "square") + 1/3. * (windowtype == "triangle")
        if (adjustedgamma == "yes"):
            ZPE[state] = ek[state] - 1 * (state == initstate)
            
        # Construct mapping variable
        q =      np.sqrt( 2 * ek[state] ) * np.cos(angle[state])
        p = -1 * np.sqrt( 2 * ek[state] ) * np.sin(angle[state])
        z[state] = q + 1j*p
    
    InitCondsFile.write( "ek-ZPE(Force_Weight)\t" + "\t".join(map(str,np.round(ek - ZPE,4)))  + "\n" )
    InitCondsFile.write( "ZPE\t\t\t" + "\t".join(map(str,np.round(ZPE,4)))  + "\n" )
    InitCondsFile.write( "ek\t\t\t" + "\t".join(map(str,np.round(ek,4))))

    return z, ZPE

    
def propagateMapVars(z, VMat):
    """
    Updates mapping variables
    Method: Velocity Verlet
    TODO Implement Runge-Kutta time-integration
    """
        
    Zreal = np.real(z)
    Zimag = np.imag(z)

    # Propagate Imaginary first by dt/2
    Zimag -= 0.5 * VMat @ Zreal * dtE

    # Propagate Real by full dt
    Zreal += VMat @ Zimag * dtE
    
    # Propagate Imaginary final by dt/2
    Zimag -= 0.5 * VMat @ Zreal * dtE

    return  Zreal + 1j*Zimag



def Force(dHel, dHel0, R, z, ZPE ):
    """
    Return force for all nuclear DOFs.
    F = F0 + Fm
    F0 = -GRAD V_0 (State-Independent)
    Fm = -GRAD V_m (State-Dependent and Traceless)
    V_m = 0.5 * SUM_(lam, u) <lam|V|u> z*_lam z'_u
    """

    action = 0.5 * np.real( np.outer( z, np.conjugate(z) ) - 2 * np.diag(ZPE) )

    F = np.zeros((len(R)))
    F -= dHel0
    for i in range(NStates):
        F -= dHel[i,i,:] * action[i,i]
        for j in range(i+1,NStates): # Double counting off-diagonal to save time
            F -= 2 * dHel[i,j,:] * action[i,j]
    return F



def VelVerF(R, P, z, ZPE): # Ionic position, ionic momentum, etc.
    """
    Routine for nuclear and electronic propagation
    Nuclear Method:    Velcoty Verlet
    """

    v = P/M
    Hel = model.Hel(R) # Electronic Structure
    dHel = model.dHel(R)
    dHel0 = model.dHel0(R)
    EStep = int(dtI/dtE)
    
    for t in range( int(EStep/2) ): # Half-step Mapping
        z = propagateMapVars(z, Hel) * 1

    F1 = Force(dHel, dHel0, R, z, ZPE )

    v += 0.5000 * F1 * dtI / M # Half-step velocity

    R += v * dtI # Full Step Position
    
    dHel = model.dHel(R)
    dHel0 = model.dHel0(R)
    F2 = Force(dHel, dHel0, R, z, ZPE )
    
    v += 0.5000 * F2 * dtI / M # Half-step Velocity

    Hel = model.Hel(R) # Electronic Structure

    for t in range( int(EStep/2) ): # Half-step Mappings
        z = propagateMapVars(z, Hel) * 1

    return R, v*M, z, Hel


def window(step, z, ZPE, densityFile, mappingFile):
    """
    Construct histogram for binning the electronic action
    TODO CONSTRUCT OFF-DIAGONAL BINS FOR COHERENCE CALCULATIONS
    """
    hist = np.ones((NStates))
    ek = np.zeros((NStates))
    
    # Get the diagonal actions for each state
    for state in range(NStates):
        ek[state] = 0.5 * np.abs( z[state] )**2 # q^2 + p^2 = (q + ip)(q - ip)

    for i in range(NStates):
        for j in range(NStates):
            if (windowtype.lower() == "square"): 
                if ( ek[j] - (i==j) < 0.0 or ek[j] - 1 > 2*0.366 ):
                    hist[i] = 0
            if (windowtype.lower() == "triangle"):
                if ( (i == j and ek[j] < 1.0) or (i != j and ek[j] >= 1.0) ):
                    hist[i] = 0

    writeDensity(step,hist,z,densityFile,mappingFile)

    return None


def writeDensity(step,hist,z,densityFile,mappingFile):

    outArray_map = [step * dtI]
    outArray_den = [step * dtI]
    for state in range(NStates):
        outArray_map.append( np.round(np.real(z[state]),4) )
        outArray_map.append( np.round(np.imag(z[state]),4) )
        outArray_den.append( int( hist[state] ) )

    mappingFile.write( "\t".join(map(str,outArray_map)) + "\n" )
    densityFile.write( "\t".join(map(str,outArray_den)) + "\n" )
    
    return None



def Run_Trajectory(traj): # This is parallelized already. "Main" for each trajectory.

    print (f"Working in traj {traj} for NSteps = {NSteps}")

    InitCondsFile, densityFile, mappingFile = initFiles(traj)

    R,P = model.initR() # Initialize nuclear DOFs
    z, ZPE = initMapping(InitCondsFile)   # Initialize electronic DOFs

    Hel = model.Hel(R)
    dHij = model.dHel(R)
    for step in range(NSteps):
        print ("Step:", step)
        if ( step % NSkip == 0 ): 
            window(step, z, ZPE, densityFile, mappingFile)
        R, P, z, Hel = VelVerF(R, P, z, ZPE)

    closeFiles(InitCondsFile, densityFile, mappingFile)

    return None
    

### Start Main Program ###
if ( __name__ == "__main__"  ):

    getGlobalParams()
    start = time.time()

    print (f"There will be {NCPUS} cores with {NTraj} trajectories.")

    runList = np.arange(NTraj)
    with mp.Pool(processes=NCPUS) as pool:
        pool.map(Run_Trajectory, runList)

    stop = time.time()
    print (f"Total Computation Time (Hours): {(stop - start) / 3600}")










