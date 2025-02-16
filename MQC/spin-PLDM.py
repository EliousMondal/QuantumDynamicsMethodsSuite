import numpy as np
import multiprocessing as mp
import time, os, sys
import Model_Tully_1 as model
import numpy.linalg as LA
import subprocess as sp
import random
import scipy as sc
from numba import jit

def getGlobalParams():
    global dtE, dtI, NSteps, NTraj, NStates, M, windowtype
    global adjustedgamma, NCPUS, initstate, dirName, method
    global fs_to_au, sampling, topDir, NSkip
    dtE = model.parameters.dtE
    dtI = model.parameters.dtI
    NSteps = model.parameters.NSteps
    NTraj = model.parameters.NTraj
    NStates = model.parameters.NStates
    M = model.parameters.M
    #sampling = model.parameters.sampling.lower()
    #windowtype = model.parameters.windowtype.lower()
    #adjustedgamma = model.parameters.adjustedgamma.lower()
    NCPUS = model.parameters.NCPUS
    initstate = model.parameters.initState # Not needed but good for checking post-processing routine
    dirName = model.parameters.dirName  + "/Partial__" + sys.argv[1] + sys.argv[2]
    topDir = model.parameters.dirName
    #method = model.parameters.method.lower()
    fs_to_au = 41.341 # a.u./fs
    NSkip = model.parameters.NSkip

def cleanMainDir():
    #if ( os.path.exists(dirName) ):
    #    sp.call("rm -r "+topDir,shell=True)
    sp.call("mkdir -p "+dirName,shell=True)

def cleanDir(n):
    if ( os.path.exists( dirName + "/traj-"+str(n) ) ):
        sp.call("rm -r "+dirName+"/traj-"+str(n),shell=True)
    sp.call("mkdir -p "+dirName+"/traj-"+str(n),shell=True)

def initFiles(n):

    densityFile = open(dirName+"/traj-" + str(n) + "/density.dat","w")
    coherenceFile = open(dirName+"/traj-" + str(n) + "/coherence.dat","w")
    InitCondsFile = open(dirName+"/traj-" + str(n) + "/initconds.dat","w")
    RFile = open(dirName+"/traj-" + str(n) + "/RFile.dat","w")
    HelFile = open(dirName+"/traj-" + str(n) + "/Hel.dat","w")
    HadFile = open(dirName+"/traj-" + str(n) + "/Had.dat","w")
    mappingFile_F = open(dirName+"/traj-" + str(n) + "/mapping_F.dat","a")
    mappingFile_B = open(dirName+"/traj-" + str(n) + "/mapping_B.dat","a")
    gamma_mat_File = open(dirName+"/traj-" + str(n) + "/gamma_mat.dat","a")
    return densityFile, InitCondsFile, RFile, HelFile, HadFile, coherenceFile, mappingFile_F, mappingFile_B, gamma_mat_File

def closeFiles(densityFile, InitCondsFile, RFile, HelFile, coherenceFile):
    densityFile.close()    
    InitCondsFile.close()
    RFile.close()
    HelFile.close()
    coherenceFile.close()

def makeArrays():
    hist = np.zeros(( NStates ))
    rho = np.zeros(( NStates,NStates ))
    Ugam = np.identity( NStates )
    return hist,rho,Ugam

def update_Gamma( Ugam, Hel ):

    E,U = np.linalg.eigh(Hel)
    Udt = U @  np.diag( np.exp( -1j * E * dtI) ) @ np.conjugate(U).T # Transform eigenvalues 
    Ugam = Udt @ Ugam # Paper says U(t_N) * U(t_N-1) * U(t_N-2) * ... 
    
    ### Potentially faster version with Scipy expm method ###
    ###### NOT TESTED !!!!! #####
    #Ugam = sc.linalg.expm( Hel )

    return Ugam

def writeDensity(densityFile,coherenceFile,z,i,z0,Ugam):

    zF0 = z0[0] # Complex 1D array
    zB0 = z0[1] # Complex 1D array

    zF = z[0] # Complex 1D array
    zB = z[1] # Complex 1D array

    gamEvolved = gw * Ugam

    if ( i % NSkip == 0 ):
        rho = np.zeros((NStates,NStates),dtype=complex)
        for n in range( NStates ):
            for m in range( NStates ):
                rho[n,m] = 0.25 * ( zB[n].conjugate() * zB0[initstate] - gamEvolved[ n,initstate ].conjugate() ) * ( zF[m] * zF0[initstate].conjugate() - gamEvolved[ m,initstate ] )


        outArrayPOP = [ round ( i * dtI ,5), round ( i * dtI / fs_to_au,5 ) ]
        outArrayCOH = [ round ( i * dtI ,5), round ( i * dtI / fs_to_au,5 ) ]

        sumPOP = 0
        for n in range(len(zF)):
            outArrayPOP.append( np.real(rho[n,n]) )
            for m in range(n+1,len(zF)):
                outArrayCOH.append( np.real( rho[n,m] ) )
                outArrayCOH.append( np.imag( rho[n,m] ) )

        densityFile.write( "\t".join(map(str,outArrayPOP)) + "\n")
        coherenceFile.write( "\t".join(map(str,outArrayCOH)) + "\n")

        #print ( "\n\t(Time, POP) :", " ".join(map(str,outArrayPOP[1:])) )

def writeKernel(z, z0, mappingFile_F, mappingFile_B, step, Ugam, gamma_mat_File):

    zF = z[0] * 1.0
    zB = z[1] * 1.0

    zF0 = z0[0] * 1.0
    zB0 = z0[1] * 1.0

    w   = 0.5 * ( np.einsum("i,j", zF[:], np.conjugate(zF0)[:] ) - gw * Ugam[:,:] )
    wp  = 0.5 * ( np.einsum("i,j", zB[:], np.conjugate(zB0)[:] ) - gw * Ugam[:,:] )
    wp = np.einsum( "ji", wp )
    wp = np.conjugate( wp )

    outF = [ round ( step * dtI ,5), round ( step * dtI / fs_to_au,5 ) ]
    outB = [ round ( step * dtI ,5), round ( step * dtI / fs_to_au,5 ) ]

    for j in range( NStates ):
        for k in range( NStates ):
            outF.append( w[j,k] )
            outB.append( wp[j,k] )

    mappingFile_F.write( "\t".join(map("{:1.5f}".format,outF)) + "\n")
    mappingFile_B.write( "\t".join(map("{:1.5f}".format,outB)) + "\n")
    
    # TrAwBw[n,m,:,traj] = np.einsum( "...ii",  A @ wp @ B @ w ) # Will compute this matrix multiplication in post-processing


def writeR(R,RFile):
    RFile.write(str(round(R[0],4)) + "\n")

def writeHel(Hel,HelFile):
    outList = []
    for i in range(NStates):
        for j in range(NStates):
            outList.append( round(Hel[i,j],6) )
    HelFile.write( "\t".join(map(str,outList))+"\n" )

def writeHad(Hel,HadFile):
    Had, U = np.linalg.eigh(Hel)
    outList = []
    for i in range(NStates):
        outList.append( round(Had[i],6) )
    HadFile.write( "\t".join(map(str,outList))+"\n" )

def initMapping(InitCondsFile):# Initialization of the mapping Variables
    """
    Returns np.array zF and zB (complex)
    """
    global gw # Only depends on the number of states. So okay to be global

    Rw = 2*np.sqrt(NStates+1) # Radius of W Sphere, not used
    gw = (2/NStates) * (np.sqrt(NStates + 1) - 1)

    # Notes:
    # Z_mu = r_mu * Exp[i phi_mu] # Cartesian mapping variables: Z = X + i P
    # r_mu = np.sqrt( 2*( mu == lambda) + gw ) # Radius of mapping var when focused to lambda

    # Initialize mapping radii
    rF = np.ones(( NStates )) * np.sqrt(gw)
    randStateF = int(sys.argv[1])
    rF[randStateF] = np.sqrt( 2 + gw )

    rB = np.ones(( NStates )) * np.sqrt(gw)
    randStateB = int(sys.argv[2])
    rB[randStateB] = np.sqrt( 2 + gw )

    zF = np.zeros(( NStates ),dtype=complex)
    zB = np.zeros(( NStates ),dtype=complex)

    ### FOCUSED spin-PLDM INITIALIZATION ###
    for i in range(NStates):
        phiF = random.random() * 2 * np.pi # Azimuthal Angle -- Always Random
        zF[i] = rF[i] * ( np.cos( phiF ) + 1j * np.sin( phiF ) )
        phiB = random.random() * 2 * np.pi # Azimuthal Angle -- Always Random
        zB[i] = rB[i] * ( np.cos( phiB ) + 1j * np.sin( phiB ) )
  
    """
    rho = np.zeros((NStates,NStates),dtype=complex)
    for n in range( NStates ):
        for m in range( NStates ):
            rho[n,m] = 0.25 * ( zF[n] * zF[initstate].conjugate() - gw * (n == initstate) ) * ( zB[m].conjugate() * zB[initstate] - gw * (m == initstate) )
    """

    z0 = np.array( [zF,zB] ) * 1.0

    return np.array( [zF,zB] ), z0

def propagateMapVars(z, VMat):
    """
    Updates mapping variables
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

@jit(nopython=True)
def Force(dHel, R, z, dHel0):
    """
    F = F0 + Fm
    F0 = -GRAD V_0 (State-Independent)
    Fm = -GRAD V_m (State-Dependent and Traceless)
    V_m = 0.5 * SUM_(lam, u) <lam|V|u> z*_lam z'_u
    """

    zF = z[0]
    zB = z[1]

    action = 0.5 * np.real( ( np.outer( zF.conjugate(), zF ) + np.outer( zB.conjugate(), zB ) - 2 * gw * np.identity(NStates) ) )

    F = np.zeros((len(R)))
    F -= dHel0
    for i in range(NStates):
        F -= 0.5 * dHel[i,i,:] * action[i,i]
        for j in range(i+1,NStates): # Double counting off-diagonal to save time
            F -= 2 * 0.5 * dHel[i,j,:] * action[i,j]
    return F

def VelVerF(R, P, z, RFile, HelFile): # Ionic position, ionic momentum, etc.
    
    v = P/M
    Hel = model.Hel(R) # Electronic Structure
    dHel = model.dHel(R)
    dHel0 = model.dHel0(R)
    EStep = int(dtI/dtE)
    
    for t in range( int(EStep/2) ): # Half-step Mapping
        z[0] = propagateMapVars(z[0], Hel) * 1
        z[1] = propagateMapVars(z[1], Hel) * 1

    
    F1 = Force(dHel, R, z, dHel0)

    v += 0.5000 * F1 * dtI / M # Half-step velocity

    R += v * dtI # Full Step Position
    
    dHel = model.dHel(R)
    dHel0 = model.dHel0(R)
    F2 = Force(dHel, R, z, dHel0)
    
    v += 0.5000 * F2 * dtI / M # Half-step Velocity

    Hel = model.Hel(R) # Electronic Structure

    for t in range( int(EStep/2) ): # Half-step Mappings
        z[0] = propagateMapVars(z[0], Hel) * 1
        z[1] = propagateMapVars(z[1], Hel) * 1

    return R, v*M, z, Hel

def RunIterations(n): # This is parallelized already. "Main" for each trajectory.

    print (f"Working in traj {n} for NSteps = {NSteps}")

    cleanDir(n)
    densityFile, InitCondsFile, RFile, HelFile, HadFile, coherenceFile, mappingFile_F, mappingFile_B, gamma_mat_File = initFiles(n) # Makes file objects
    hist,rho,Ugam = makeArrays()

    R,P = model.initR() # Initialize nuclear DOF

    z,z0 = initMapping(InitCondsFile)

    Hel = model.Hel(R)
    dHij = model.dHel(R)
    for step in range(NSteps):
        #print ("Step:", step)
        if ( step % NSkip == 0 ):
            writeHel(Hel,HelFile)
            writeHad(Hel,HadFile)
            #writeDensity(densityFile,coherenceFile,z,step,z0,Ugam)
            writeKernel( z, z0, mappingFile_F, mappingFile_B, step, Ugam, gamma_mat_File )
        R, P, z, Hel = VelVerF(R, P, z, RFile, HelFile)
        Ugam = update_Gamma( Ugam, Hel )
        
        
    
    closeFiles(densityFile, InitCondsFile, RFile, HelFile, coherenceFile)


### Start Main Program ###
if ( __name__ == "__main__"  ):

    getGlobalParams()
    cleanMainDir()
    start = time.time()

    print (f"There will be {NCPUS} cores with {NTraj} trajectories.")

    runList = np.arange(NTraj)
    with mp.Pool(processes=NCPUS) as pool:
        pool.map(RunIterations,runList)

    stop = time.time()
    print (f"Total Computation Time (Hours): {(stop - start) / 3600}")


