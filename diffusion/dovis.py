import numpy
import pylab

from util import runparams

def dovis(myData, n):

    pylab.clf()

    phi = myData.getVarPtr("phi")

    myg = myData.grid

    pylab.imshow(numpy.transpose(phi[myg.ilo:myg.ihi+1,myg.jlo:myg.jhi+1]), 
                 interpolation="nearest", origin="lower",
                 extent=[myg.xmin, myg.xmax, myg.ymin, myg.ymax])

    pylab.xlabel("x")
    pylab.ylabel("y")
    pylab.title("phi")

    pylab.colorbar()

    pylab.figtext(0.05,0.0125, "t = %10.5f" % myData.t)

    pylab.draw()

