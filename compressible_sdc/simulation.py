from __future__ import print_function

import numpy as np

import mesh.integration as integration
import mesh.fv as fv
import mesh.patch as patch
import compressible_fv4
import compressible_fv4.fluxes as flx
from util import msg

class Simulation(compressible_fv4.Simulation):

    def __init__(self, solver_name, problem_name, rp, timers=None):
        super().__init__(solver_name, problem_name, rp, timers=timers, data_class=fv.FV2d)

    def initialize(self):
        super().initialize(ng=5)

    def preevolve(self):
        """Since we are 4th order accurate we need to make sure that we
        initialized with accurate zone-averages, so the preevolve for
        this solver assumes that the initialization was done to
        cell-centers and converts it to cell-averages."""

        # we just initialized cell-centers, but we need to store averages
        for var in self.cc_data.names:
            self.cc_data.from_centers(var)

    def sdc_integral(self, m_start, m_end, As):
        """Compute the integral over the sources from m to m+1 with a
        Simpson's rule"""

        I = self.cc_data.grid.scratch_array(nvar=self.ivars.nvar)

        if m_start == 0 and m_end == 1:
            for n in range(self.ivars.nvar):
                I.v(n=n)[:,:] = self.dt/24.0 * (5.0*As[0].v(n=n) + 8.0*As[1].v(n=n) - As[2].v(n=n))

        elif m_start == 1 and m_end == 2:
            for n in range(self.ivars.nvar):
                I.v(n=n)[:,:] = self.dt/24.0 * (-As[0].v(n=n) + 8.0*As[1].v(n=n) + 5.0*As[2].v(n=n))

        else:
            msg.fail("invalid quadrature range")

        return I

    def evolve(self):

        """
        Evolve the equations of compressible hydrodynamics through a
        timestep dt.
        """

        tm_evolve = self.tc.timer("evolve")
        tm_evolve.begin()

        myd = self.cc_data

        # we need the solution at 3 time points and at the old and
        # current iteration (except for m = 0 -- that doesn't change).

        # This copy will initialize the the solution at all time nodes
        # with the current (old) solution.
        U_kold = []
        U_kold.append(patch.cell_center_data_clone(self.cc_data))
        U_kold.append(patch.cell_center_data_clone(self.cc_data))
        U_kold.append(patch.cell_center_data_clone(self.cc_data))

        U_knew = []
        U_knew.append(U_kold[0])
        U_knew.append(patch.cell_center_data_clone(self.cc_data))
        U_knew.append(patch.cell_center_data_clone(self.cc_data))

        # loop over iterations
        for k in range(1, 5):

            # we need the advective term at all time nodes at the old
            # iteration -- we'll compute this now
            A_kold = []
            for m in range(3):
                _tmp = self.substep(U_kold[m])
                A_kold.append(_tmp)

            # loop over the time nodes and update
            for m in range(2):

                # update m to m+1 for knew

                # compute A(U_m^{k+1})
                A_knew = self.substep(U_knew[m])

                # compute the integral over A at the old iteration
                I = self.sdc_integral(m, m+1, A_kold)

                # and the final update
                for n in range(self.ivars.nvar):
                    U_knew[m+1].data.v(n=n)[:,:] = U_knew[m].data.v(n=n) + \
                       0.5*self.dt * (A_knew.v(n=n) - A_kold[m].v(n=n)) + I.v(n=n)

                # fill ghost cells
                U_knew[m+1].fill_BC_all()

            # store the current iteration as the old iteration
            for m in range(1, 3):
                U_kold[m].data[:,:,:] = U_knew[m].data[:,:,:]


        # store the new solution
        self.cc_data.data[:,:,:] = U_knew[-1].data[:,:,:]

        # increment the time
        myd.t += self.dt
        self.n += 1

        tm_evolve.end()