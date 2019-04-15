import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import AxesGrid
import importlib

from mesh import patch
from mesh import integration

from simulation_null import NullSimulation, grid_setup_1d, bc_setup_1d
import util.plot_tools as plot_tools

from hydro_base.eos import GammaLawEOS
from hydro_base.reconstruct import MinmodReconstruct1D
from hydro_base.riemann import HLLE1D, Rusanov1D
import hydro_base.variables as vars

from sr_compressible.equations import CompressibleSR1D, lorentz_and_vel


class Simulation(NullSimulation):

    def __init__(self, solver_name, problem_name, rp, timers=None,
                 data_class=patch.CellCenterData1d):
        super().__init__(solver_name, problem_name, rp, timers, data_class)

    def initialize(self):

        my_grid = grid_setup_1d(self.rp, ng=2)

        # create the variables
        my_data = patch.CellCenterData1d(my_grid)
        bc = bc_setup_1d(self.rp)[0]

        # Primitives
        my_data.register_var("rho0", bc)
        my_data.register_var("u", bc)
        my_data.register_var("eps", bc)

        # Conserved
        my_data.register_var("D", bc)
        my_data.register_var("S", bc)
        my_data.register_var("E", bc)

        # store the EOS gamma as an auxillary quantity so we can have a
        # self-contained object stored in output files to make plots.
        gamma = self.rp.get_param("eos.gamma")
        my_data.set_aux("gamma", gamma)

        my_data.create()

        self.cc_data = my_data

        # Setup solver stuff
        self.eos = GammaLawEOS(gamma)
        self.eqns = CompressibleSR1D(self.eos)
        self.reconstruct = MinmodReconstruct1D()

        riemann_solvers = {"hlle": HLLE1D, "rusanov": Rusanov1D}
        rsolver = self.rp.get_param("sr_compressible.riemann").lower()
        print("Using", rsolver, "Riemann solver")
        self.riemann = riemann_solvers[rsolver](self.eqns)

        # Setup temp storage for calculations
        shape = (my_grid.qx,)

        # Cell-centered values
        self.U = [vars.ConservedVector1D(shape) for i in range(3)]
        self.V = vars.PrimitiveVector1D(shape)
        self.char = vars.CharacteristicVector1D(shape)
        self.source = vars.SourceVector1D(shape)

        self.F = vars.FluxVector1D((my_grid.qx+1,))

        self.dU = vars.ConservedVector1D(shape)
        self.U_new = vars.ConservedVector1D(shape)

        # Left-face values
        self.U_l = vars.ConservedVector1D(shape)
        self.V_l = vars.PrimitiveVector1D(shape)
        self.F_l = vars.FluxVector1D(shape)
        self.char_l = vars.CharacteristicVector1D(shape)

        # Right-face values
        self.U_r = vars.ConservedVector1D(shape)
        self.V_r = vars.PrimitiveVector1D(shape)
        self.F_r = vars.FluxVector1D(shape)
        self.char_r = vars.CharacteristicVector1D(shape)

        # now set the initial conditions for the problem
        problem = importlib.import_module("sr_compressible.problems.{}".format(self.problem_name))
        problem.init_data(self.cc_data, self.rp, self.eqns)

        self.load_from_patch(0)

    def method_compute_timestep(self):
        """
        Compute the advective timestep (CFL) constraint.  We use the
        driver.cfl parameter to control what fraction of the CFL
        step we actually take.
        """

        cfl = self.rp.get_param("driver.cfl")
        dx = self.cc_data.grid.dx
        ng = self.cc_data.grid.ng

        self.eqns.speeds(self.U[0], self.V, self.char)

        self.dt = cfl*np.min(dx/np.max(np.abs(self.char[:, ng:-ng]), axis=0))

    def RHS(self):
        dx = self.cc_data.grid.dx
        ng = self.cc_data.grid.ng

        self.reconstruct.interface_states(self.cc_data.grid,
                                          self.V, self.V_l, self.V_r)

        self.eqns.prim2con(self.V_l, self.U_l)
        self.eqns.prim2con(self.V_r, self.U_r)

        self.eqns.fluxes(self.U_l, self.V_l, self.F_l)
        self.eqns.fluxes(self.U_r, self.V_r, self.F_r)

        self.eqns.speeds(self.U_l, self.V_l, self.char_l)
        self.eqns.speeds(self.U_r, self.V_r, self.char_r)

        self.F[:, 0] = self.F[:, -1] = 0.0
        self.riemann.fluxes(self.U_l[:, :-1], self.U_r[:, 1:],
                            self.V_l[:, :-1], self.V_r[:, 1:],
                            self.F_l[:, :-1], self.F_r[:, 1:],
                            self.char_l[:, :-1], self.char_r[:, 1:],
                            self.F[:, 1:-1])

        self.dU[:] = 0.0
        self.dU[:] -= np.diff(self.F, axis=1)
        self.dU[:] /= dx

        self.eqns.sources(self.U, self.V, self.source)
        self.dU[:] += self.source[:]

        self.dU[:, :ng] = 0.0
        self.dU[:, -ng:] = 0.0

    def apply_BC_hack(self, level):
        ng = self.cc_data.grid.ng

        D = self.cc_data.get_var("D")
        S = self.cc_data.get_var("S")
        E = self.cc_data.get_var("E")

        D.v()[:] = self.U[level].density[ng:-ng]
        S.v()[:] = self.U[level].momentum[ng:-ng]
        E.v()[:] = self.U[level].energy[ng:-ng]

        self.cc_data.fill_BC_all()

    def save_to_patch(self, level):
        ng = self.cc_data.grid.ng
        D = self.cc_data.get_var("D")
        S = self.cc_data.get_var("S")
        E = self.cc_data.get_var("E")

        rho0 = self.cc_data.get_var("rho0")
        u = self.cc_data.get_var("u")
        eps = self.cc_data.get_var("eps")

        D.v()[:] = self.U[level].density[ng:-ng]
        S.v()[:] = self.U[level].momentum[ng:-ng]
        E.v()[:] = self.U[level].energy[ng:-ng]

        rho0.v()[:] = self.V.density[ng:-ng]
        u.v()[:] = self.V.velocity[ng:-ng]
        eps.v()[:] = self.V.specific_energy[ng:-ng]

    def load_from_patch(self, level):
        ng = self.cc_data.grid.ng
        D = self.cc_data.get_var("D")
        S = self.cc_data.get_var("S")
        E = self.cc_data.get_var("E")

        rho0 = self.cc_data.get_var("rho0")
        u = self.cc_data.get_var("u")
        eps = self.cc_data.get_var("eps")

        self.U[level].density = D[:]
        self.U[level].momentum = S[:]
        self.U[level].energy = E[:]

        self.V.density = rho0[:]
        self.V.velocity = u[:]
        self.V.specific_energy = eps[:]

    def evolve(self):
        """
        Evolve the equations of special relativistic compressible
        hydrodynamics through a timestep dt.
        """
        tm_evolve = self.tc.timer("evolve")
        tm_evolve.begin()

        # First step
        self.RHS()
        self.U[1][:] = self.U[0][:] + self.dt*self.dU
        self.apply_BC_hack(1)
        self.eqns.con2prim(self.U[1], self.V)

        # Second step
        self.RHS()
        self.U[2][:] = 0.5*(self.U[0][:] + self.U[1][:] + self.dt*self.dU)
        self.apply_BC_hack(2)
        self.eqns.con2prim(self.U[2], self.V)

        # Rotate time levels
        U = self.U[0]
        self.U[0] = self.U[2]
        self.U[2] = self.U[1]
        self.U[1] = U

        self.save_to_patch(0)

        # increment the time
        self.cc_data.t += self.dt
        self.n += 1

        tm_evolve.end()

    def dovis(self):
        """
        Do runtime visualization.
        """

        plt.clf()

        plt.rc("font", size=10)

        rho0 = self.cc_data.get_var("rho0")
        u = self.cc_data.get_var("u")
        eps = self.cc_data.get_var("eps")
        P = self.eos.pressure(rho0, eps)
        W, v = lorentz_and_vel(u)

        myg = self.cc_data.grid

        fields = [rho0, v, P, eps]
        field_names = ["\\rho_0", "v", "P", "\\epsilon"]

        # _, axes, cbar_title = plot_tools.setup_axes_1d(myg, len(fields))

        _, axs = plt.subplots(2, 2, sharex=True, constrained_layout=True,
                              num=1)
        # fig = plt.figure(1, (10.5, 2.5))
        # fig.subplots_adjust(left=0.05, right=0.95)
        # axs = AxesGrid(fig, 141,
        #             nrows_ncols=(2, 2),
        #             share_all=True,
        #             # cbar_mode="each",
        #             # cbar_location="top",
        #             # cbar_pad="10%",
        #             # cbar_size="25%",
        #             axes_pad=(0.25, 0.65),
        #             add_all=True, label_mode="L")

        x = myg.x[myg.ng:-myg.ng]

        for n in range(len(fields)):
            var = fields[n]

            i = n // 2
            j = n % 2

            axs[i, j].plot(x, var.v())

            axs[i, j].set_xlabel("$x$")
            axs[i, j].set_ylabel("${:s}$".format(field_names[n]))

            axs[i, j].set_title("${:s}$".format(field_names[n]))

        plt.figtext(0.05, 0.0125, "t = {:10.5f}".format(self.cc_data.t))

        plt.pause(0.001)
        plt.draw()
