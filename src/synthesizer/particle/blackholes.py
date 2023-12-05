"""A module for working with arrays of black holes.

Contains the BlackHoles class for use with particle based systems. This houses
all the data detailing collections of black hole particles. Each property is
stored in (N_bh, ) shaped arrays for efficiency.

When instantiate a BlackHoles object a myriad of extra optional properties can
be set by providing them as keyword arguments.

Example usages:

    bhs = BlackHoles(masses, metallicities,
                     redshift=redshift, accretion_rate=accretion_rate, ...)
"""
import numpy as np
from unyt import rad

from synthesizer.particle.particles import Particles
from synthesizer.components import BlackholesComponent
from synthesizer.blackhole_emission_models import Template
from synthesizer import exceptions
from synthesizer.units import Quantity
from synthesizer.utils import value_to_array


class BlackHoles(Particles, BlackholesComponent):
    """
    The base BlackHoles class. This contains all data a collection of black
    holes could contain. It inherits from the base Particles class holding
    attributes and methods common to all particle types.

    The BlackHoles class can be handed to methods elsewhere to pass information
    about the stars needed in other computations. For example a Galaxy object
    can be initialised with a BlackHoles object for use with any of the Galaxy
    helper methods.

    Note that due to the many possible operations, this class has a large
    number of optional attributes which are set to None if not provided.

    Attributes:
        nbh (int)
            The number of black hole particles in the object.
        smoothing_lengths (array-like, float)
            The smoothing length describing the black holes neighbour kernel.
        particle_spectra (dict)
            A dictionary of Sed objects containing any of the generated
            particle spectra.
    """

    # Define the allowed attributes
    attrs = [
        "_masses",
        "_coordinates",
        "_velocities",
        "metallicities",
        "nparticles",
        "redshift",
        "_accretion_rate",
        "_bb_temperature",
        "_bolometric_luminosity",
        "_softening_lengths",
        "_smoothing_lengths",
        "nbh",
    ]

    # Define quantities
    smoothing_lengths = Quantity()

    def __init__(
        self,
        masses,
        accretion_rates,
        epsilons=0.1,
        inclinations=None,
        spins=None,
        metallicities=None,
        redshift=None,
        coordinates=None,
        velocities=None,
        softening_length=None,
        smoothing_lengths=None,
        **kwargs,
    ):
        """
        Intialise the Stars instance. The first two arguments are always
        required. All other arguments are optional attributes applicable
        in different situations.

        Args:
            masses (array-like, float)
                The mass of each particle in Msun.
            metallicities (array-like, float)
                The metallicity of the region surrounding the/each black hole.
            epsilons (array-like, float)
                The radiative efficiency. By default set to 0.1.
            inclination (array-like, float)
                The inclination of the blackhole. Necessary for many emission
                models.
            redshift (float)
                The redshift/s of the black hole particles.
            accretion_rate (array-like, float)
                The accretion rate of the/each black hole in Msun/yr.
            coordinates (array-like, float)
                The 3D positions of the particles.
            velocities (array-like, float)
                The 3D velocities of the particles.
            softening_length (float)
                The physical gravitational softening length.
            smoothing_lengths (array-like, float)
                The smoothing length describing the black holes neighbour
                kernel.
            kwargs (dict)
                Any parameter for the emission models can be provided as kwargs
                here to override the defaults of the emission models.
        """

        # Handle singular values being passed (arrays are just returned)
        masses = value_to_array(masses)
        accretion_rates = value_to_array(accretion_rates)
        epsilons = value_to_array(epsilons)
        inclinations = value_to_array(inclinations)
        spins = value_to_array(spins)
        metallicities = value_to_array(metallicities)
        smoothing_lengths = value_to_array(smoothing_lengths)

        # Instantiate parents
        Particles.__init__(
            self,
            coordinates=coordinates,
            velocities=velocities,
            masses=masses,
            redshift=redshift,
            softening_length=softening_length,
            nparticles=len(masses),
        )
        BlackholesComponent.__init__(
            self,
            mass=masses,
            accretion_rate=accretion_rates,
            epsilon=epsilons,
            inclination=inclinations,
            spin=spins,
            metallicity=metallicities,
            **kwargs,
        )

        # Set a frontfacing clone of the number of particles with clearer
        # naming
        self.nbh = self.nparticles

        # Make pointers to the singular black hole attributes for consistency
        # in the backend
        for singular, plural in [
            ("mass", "masses"),
            ("accretion_rate", "accretion_rates"),
            ("metallicity", "metallicities"),
            ("spin", "spins"),
            ("inclination", "inclinations"),
            ("epsilon", "epsilons"),
            ("bb_temperature", "bb_temperatures"),
            ("bolometric_luminosity", "bolometric_luminosities"),
            ("accretion_rate_eddington", "accretion_rates_eddington"),
            ("epsilon", "epsilons"),
            ("eddington_ratio", "eddington_ratios"),
        ]:
            setattr(self, plural, getattr(self, singular))

        # Set the smoothing lengths
        self.smoothing_lengths = smoothing_lengths

        # Check the arguments we've been given
        self._check_bh_args()

        # Define the particle spectra dictionary
        self.particle_spectra = {}

    def _check_bh_args(self):
        """
        Sanitizes the inputs ensuring all arguments agree and are compatible.

        Raises:
            InconsistentArguments
                If any arguments are incompatible or not as expected an error
                is thrown.
        """

        # Ensure all arrays are the expected length
        for key in self.attrs:
            attr = getattr(self, key)
            if isinstance(attr, np.ndarray):
                if attr.shape[0] != self.nparticles:
                    raise exceptions.InconsistentArguments(
                        "Inconsistent black hole array sizes! (nparticles=%d, "
                        "%s=%d)" % (self.nparticles, key, attr.shape[0])
                    )

    def calculate_random_inclination(self):
        """
        Calculate random inclinations to blackholes.
        """

        self.inclination = (
            np.random.uniform(low=0.0, high=np.pi / 2.0, size=self.nbh) * rad
        )

        self.cosine_inclination = np.cos(self.inclination.to("rad").value)

    def _prepare_sed_args(
        self,
        grid,
        fesc,
        spectra_type,
        grid_assignment_method,
    ):
        """
        A method to prepare the arguments for SED computation with the C
        functions.

        Args:
            grid (Grid)
                The SPS grid object to extract spectra from.
            fesc (float)
                The escape fraction.
            spectra_type (str)
                The type of spectra to extract from the Grid. This must match a
                type of spectra stored in the Grid.
            grid_assignment_method (string)
                The type of method used to assign particles to a SPS grid
                point. Allowed methods are cic (cloud in cell) or nearest
                grid point (ngp) or there uppercase equivalents (CIC, NGP).
                Defaults to cic.

        Returns:
            tuple
                A tuple of all the arguments required by the C extension.
        """

        # Set up the inputs to the C function.
        grid_props = [
            np.ascontiguousarray(getattr(grid, axis), dtype=np.float64)
            for axis in grid.axes
        ]
        props = [
            np.ascontiguousarray(getattr(self, axis), dtype=np.float64)
            for axis in grid.axes
        ]

        # For black holes mass is a grid parameter but we still need to
        # multiply by mass in the extensions so just multiply by 1
        mass = np.ones(self.nbh, dtype=np.float64)

        # Make sure we get the wavelength index of the grid array
        nlam = np.int32(grid.spectra[spectra_type].shape[-1])

        # Get the grid spctra
        grid_spectra = np.ascontiguousarray(
            grid.spectra[spectra_type],
            dtype=np.float64,
        )

        # Get the grid dimensions after slicing what we need
        grid_dims = np.zeros(len(grid_props) + 1, dtype=np.int32)
        for ind, g in enumerate(grid_props):
            grid_dims[ind] = len(g)
        grid_dims[ind + 1] = nlam

        # Convert inputs to tuples
        grid_props = tuple(grid_props)
        props = tuple(props)

        return (
            grid_spectra,
            grid_props,
            props,
            mass,
            fesc,
            grid_dims,
            len(grid_props),
            np.int32(self.nbh),
            nlam,
            grid_assignment_method,
        )

    def _generate_particle_lnu(
        self,
        grid,
        spectra_name,
        fesc=0.0,
        verbose=False,
        grid_assignment_method="cic",
    ):
        """
        Generate the integrated rest frame spectra for a given grid key
        spectra.

        Args:
            grid (obj):
                Spectral grid object.
            fesc (float):
                Fraction of emission that escapes unattenuated from
                the birth cloud (defaults to 0.0).
            spectra_name (string)
                The name of the target spectra inside the grid file
                (e.g. "incident", "transmitted", "nebular").
            verbose (bool)
                Are we talking?
            grid_assignment_method (string)
                The type of method used to assign particles to a SPS grid
                point. Allowed methods are cic (cloud in cell) or nearest
                grid point (ngp) or there uppercase equivalents (CIC, NGP).
                Defaults to cic.
        """
        # Ensure we have a key in the grid. If not error.
        if spectra_name not in list(grid.spectra.keys()):
            raise exceptions.MissingSpectraType(
                f"The Grid does not contain the key '{spectra_name}'"
            )

        from ..extensions.particle_spectra import compute_particle_seds

        # Prepare the arguments for the C function.
        args = self._prepare_sed_args(
            grid,
            fesc=fesc,
            spectra_type=spectra_name,
            grid_assignment_method=grid_assignment_method.lower(),
        )

        # Get the integrated spectra in grid units (erg / s / Hz)
        return compute_particle_seds(*args)

    def _get_particle_spectra_disc(
        self,
        emission_model,
        verbose,
        grid_assignment_method,
    ):
        """
        Generate the disc spectra for each particle, updating the parameters
        if required.

        Args:
            emission_model (blackhole_emission_models.*)
                Any instance of a blackhole emission model (e.g. Template
                or UnifiedAGN)
            verbose (bool)
                Are we talking?
            grid_assignment_method (string)
                The type of method used to assign particles to a SPS grid
                point. Allowed methods are cic (cloud in cell) or nearest
                grid point (ngp) or there uppercase equivalents (CIC, NGP).
                Defaults to cic.

        Returns:
            dict, Sed
                A dictionary of Sed instances including the escaping and
                transmitted disc emission for each particle.
        """

        # Get the wavelength array
        lam = emission_model.grid["nlr"].lam

        # Calculate the incident spectra. It doesn't matter which spectra we
        # use here since we're just using the incident. Note: this assumes the
        # NLR and BLR are not overlapping.
        self.particle_spectra["disc_incident"] = Sed(
            lam,
            self.generate_particle_lnu(
                emission_model.grid["nlr"],
                spectra_name="incident",
                fesc=0.0,
                verbose=verbose,
                grid_assignment_method=grid_assignment_method,
            ),
        )

        # calculate the transmitted spectra
        nlr_spectra = self.generate_particle_lnu(
            emission_model.grid["nlr"],
            spectra_name="transmitted",
            fesc=self.covering_fraction_nlr,
            verbose=verbose,
            grid_assignment_method=grid_assignment_method,
        )
        blr_spectra = self.generate_particle_lnu(
            emission_model.grid["blr"],
            spectra_name="transmitted",
            fesc=self.covering_fraction_blr,
            verbose=verbose,
            grid_assignment_method=grid_assignment_method,
        )
        self.particle_spectra["disc_transmitted"] = Sed(lam, nlr_spectra + blr_spectra)

        # calculate the escaping spectra.
        self.particle_spectra["disc_escaped"] = Sed(
            lam,
            (1 - self.covering_fraction_blr - self.covering_fraction_nlr)
            * self.particle_spectra["disc_incident"],
        )

        # calculate the total spectra, the sum of escaping and transmitted
        self.particle_spectra["disc"] = Sed(
            lam,
            self.particle_spectra["disc_transmitted"]._lnu
            + self.particle_spectra["disc_escaped"]._lnu,
        )

        return self.particle_spectra["disc"]

    def _get_particle_spectra_lr(
        self,
        emission_model,
        line_region,
        verbose,
        grid_assignment_method,
    ):
        """
        Generate the spectra of a generic line region of each particle.

        Args
            emission_model (blackhole_emission_models.*)
                Any instance of a blackhole emission model (e.g. Template
                or UnifiedAGN)
            line_region (str)
                The specific line region, i.e. 'nlr' or 'blr'.
            verbose (bool)
                Are we talking?
            grid_assignment_method (string)
                The type of method used to assign particles to a SPS grid
                point. Allowed methods are cic (cloud in cell) or nearest
                grid point (ngp) or there uppercase equivalents (CIC, NGP).
                Defaults to cic.

        Returns:
            Sed
                The NLR spectra of each particle.
        """

        # In the Unified AGN model the NLR/BLR is illuminated by the isotropic
        # disc emisison hence the need to replace this parameter if it exists.
        # Not all models require an inclination though.
        prev_cosine_inclincation = self.cosine_inclination
        self.cosine_inclination = 0.5

        # Get the nebular spectra of the line region
        spec = self.generate_particle_lnu(
            emission_model.grid[line_region],
            spectra_name="nebular",
            fesc=0.0,
            verbose=verbose,
            grid_assignment_method=grid_assignment_method,
        )
        sed = Sed(
            emission_model.grid[line_region]._lam,
            getattr(self, "covering_fraction_{line_region}") * spec,
        )

        # Reset the previously held inclination
        self.cosine_inclination = prev_cosine_inclincation

        return sed

    def _get_particle_spectra_torus(
        self,
        emission_model,
        verbose,
        grid_assignment_method,
    ):
        """
        Generate the torus emission Sed of each particle.

        Args:
            emission_model (blackhole_emission_models.*)
                Any instance of a blackhole emission model (e.g. Template
                or UnifiedAGN)
            verbose (bool)
                Are we talking?
            grid_assignment_method (string)
                The type of method used to assign particles to a SPS grid
                point. Allowed methods are cic (cloud in cell) or nearest
                grid point (ngp) or there uppercase equivalents (CIC, NGP).
                Defaults to cic.

        Returns:
            Sed
                The torus spectra of each particle.
        """

        # In the Unified AGN model the torus is illuminated by the isotropic
        # disc emisison hence the need to replace this parameter if it exists.
        # Not all models require an inclination though.
        prev_cosine_inclincation = self.cosine_inclination
        self.cosine_inclination = 0.5

        # Calcualte the disc emission, since this is incident it doesn't matter
        # if we use the NLR or BLR grid as long as we use the correct grid
        # point.
        disc_spectra = self.generate_particle_lnu(
            emission_model.grid["nlr"],
            spectra_name="incident",
            fesc=0.0,
            verbose=verbose,
            grid_assignment_method=grid_assignment_method,
        )

        # calculate the bolometric dust lunminosity as the difference between
        # the intrinsic and attenuated
        torus_bolometric_luminosity = (
            self.theta_torus / (90 * deg)
        ) * disc_spectra.measure_bolometric_luminosity()

        # create torus spectra
        sed = emission_model.torus_emission_model.get_spectra(disc_spectra.lam)

        # this is normalised to a bolometric luminosity of 1 so we need to
        # scale by the bolometric luminosity.

        sed._lnu *= torus_bolometric_luminosity.value

        # Reset the previously held inclination
        self.cosine_inclination = prev_cosine_inclincation

        return sed

    def get_particle_spectra_intrinsic(
        self,
        emission_model,
        verbose=True,
        grid_assignment_method="cic",
    ):
        """
        Generate intrinsic blackhole spectra for a given emission_model for
        each particle.

        Args:
            emission_model (blackhole_emission_models.*)
                Any instance of a blackhole emission model (e.g. Template
                or UnifiedAGN)
            verbose (bool)
                Are we talking?
            grid_assignment_method (string)
                The type of method used to assign particles to a SPS grid
                point. Allowed methods are cic (cloud in cell) or nearest
                grid point (ngp) or there uppercase equivalents (CIC, NGP).
                Defaults to cic.

        Returns:
            dict, Sed
                A dictionary of Sed instances including the intrinsic emission
                of each particle.
        """

        # Early exit if the emission model is a Template, for this we just
        # return the template scaled by bolometric luminosity
        if isinstance(emission_model, Template):
            self.particle_spectra["intrinsic"] = emission_model.get_particle_spectra(
                self.bolometric_luminosity
            )
            return self.particle_spectra

        # Set any parameter this particular emission model requires which
        # are not set on the object. These are unset at the end of the method!
        used_defaults = []
        for param in emission_model.variable_parameters:
            # Get the parameter value from this object
            attr = getattr(self, param, None)
            priv_attr = getattr(self, "_" + param, None)

            # Is it set?
            if (
                attr is None
                and priv_attr is None
                and param in emission_model.fixed_parameters_dict
            ):
                # Ok, this one needs setting based on the model
                default = emission_model.fixed_parameters_dict[param]
                setattr(self, param, default)

                # Record that we used a fixed parameter for removal later
                used_defaults.append(param)

                if verbose:
                    print(f"{param} wasn't set, fixing it to {default}")

        # Check if we have all the required parameters, if not raise an
        # exception and tell the user which are missing. Bolometric luminosity
        # is not strictly required.
        missing_params = []
        for param in emission_model.parameters:
            # Skip bolometric luminosity
            if param == "bolometric_luminosity":
                continue

            # Get the parameter value from this object
            attr = getattr(self, param, None)
            priv_attr = getattr(self, "_" + param, None)

            # Is it set?
            if attr is None and priv_attr is None:
                missing_params.append(param)

        if len(missing_params) > 0:
            raise exceptions.MissingArgument(
                "Parameters are missing and can't be fixed by"
                f" the model: {missing_params}"
            )

        # Determine the inclination from the cosine_inclination
        inclination = np.arccos(self.cosine_inclination) * rad

        # If the inclination is too high (edge) on we don't see the disc, only
        # the NLR and the torus.
        if inclination < ((90 * deg) - self.theta_torus):
            self._get_particle_spectra_disc(
                emission_model=emission_model,
                verbose=verbose,
                grid_assignment_method=grid_assignment_method,
            )
            self.particle_spectra["blr"] = self._get_particle_spectra_lr(
                emission_model=emission_model,
                verbose=verbose,
                grid_assignment_method=grid_assignment_method,
                line_region="blr",
            )

        self.particle_spectra["nlr"] = self._get_particle_spectra_lr(
            emission_model=emission_model,
            verbose=verbose,
            grid_assignment_method=grid_assignment_method,
            line_region="nlr",
        )
        self.particle_spectra["torus"] = self._get_particle_spectra_torus(
            emission_model=emission_model,
            verbose=verbose,
            grid_assignment_method=grid_assignment_method,
        )

        # If we don't see the BLR and disc still generate spectra but set them
        # to zero
        if inclination >= ((90 * deg) - self.theta_torus):
            for spectra_id in [
                "blr",
                "disc_transmitted",
                "disc_incident",
                "disc_escape",
                "disc",
            ]:
                self.particle_spectra[spectra_id] = Sed(
                    lam=self.particle_spectra["nlr"].lam
                )

        # Calculate the emergent spectra as the sum of the components.
        # Note: the choice of "intrinsic" is to align with the Pacman model
        # which reserves "total" and "emergent" to include dust.
        self.particle_spectra["intrinsic"] = (
            self.particle_spectra["disc"]
            + self.particle_spectra["blr"]
            + self.particle_spectra["nlr"]
            + self.particle_spectra["torus"]
        )

        # Since we're using a coarse grid it might be necessary to rescale
        # the spectra to the bolometric luminosity. This is requested when
        # the emission model is called from a parametric or particle blackhole.
        if self.bolometric_luminosity is not None:
            scaling = (
                self.bolometric_luminosity
                / self.particle_spectra["intrinsic"].measure_bolometric_luminosity()
            )
            for spectra_id, spectra in self.particle_spectra.items():
                self.particle_spectra[spectra_id] = spectra * scaling

        # Unset any of the fixed parameters we had to inherit
        for param in used_defaults:
            setattr(self, param, None)

        return self.particle_spectra

    def get_particle_spectra_attenuated(
        self,
        emission_model,
        verbose=True,
        grid_assignment_method="cic",
        tau_v=None,
        dust_curve=None,
        dust_emission_model=None,
    ):
        """
        Generate blackhole spectra for a given emission_model including
        dust attenuation and potentially emission for each particle.

        Args:
            emission_model (blackhole_emission_models.*)
                Any instance of a blackhole emission model (e.g. Template
                or UnifiedAGN)
            verbose (bool)
                Are we talking?
            grid_assignment_method (string)
                The type of method used to assign particles to a SPS grid
                point. Allowed methods are cic (cloud in cell) or nearest
                grid point (ngp) or there uppercase equivalents (CIC, NGP).
                Defaults to cic.
            tau_v (float)
                The v-band optical depth.
            dust_curve (object)
                A synthesizer dust.attenuation.AttenuationLaw instance.
            dust_emission_model (object)
                A synthesizer dust.emission.DustEmission instance.

        Returns:
            dict, Sed
                A dictionary of Sed instances including the intrinsic and
                attenuated emission of each particle.
        """

        # Generate the intrinsic spectra
        self.get_particle_spectra_intrinsic(
            emission_model=emission_model,
            verbose=verbose,
            grid_assignment_method=grid_assignment_method,
        )

        # If dust attenuation is provided then calcualate additional spectra
        if dust_curve is not None and tau_v is not None:
            intrinsic = self.particle_spectra["intrinsic"]
            self.particle_spectra["emergent"] = intrinsic.apply_attenuation(
                tau_v, dust_curve=dust_curve
            )

            # If a dust emission model is also provided then calculate the
            # dust spectrum and total emission.
            if dust_emission_model is not None:
                # ISM dust heated by old stars.
                dust_bolometric_luminosity = (
                    self.particle_spectra["intrinsic"].bolometric_luminosity
                    - self.particle_spectra["emergent"].bolometric_luminosity
                )

                # Calculate normalised dust emission spectrum
                self.particle_spectra[
                    "dust"
                ] = dust_emission_model.get_particle_spectra(
                    self.particle_spectra["emergent"].lam
                )

                # Scale the dust spectra by the dust_bolometric_luminosity.
                self.particle_spectra["dust"]._lnu *= dust_bolometric_luminosity.value

                # Calculate total spectrum
                self.particle_spectra["total"] = (
                    self.particle_spectra["emergent"] + self.particle_spectra["dust"]
                )

        elif (dust_curve is not None) or (tau_v is not None):
            raise exceptions.MissingArgument(
                "To enable dust attenuation both 'dust_curve' and "
                "'tau_v' need to be provided."
            )

        return self.particle_spectra
