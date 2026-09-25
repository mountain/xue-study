"""Analytic and adversarial checks for typed spherical representations."""
import unittest
import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.linalg import expm
from scipy.special import eval_legendre

from spectrum import (SphereBasis, advection_operator, fit, gaussian_grid,
                      kernel_multipliers, latlon_points, local_tensor_response,
                      local_vector_response, recover_local_tensor,
                      recover_local_vector, response)


class SpectrumChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.points, cls.weights = gaussian_grid()
        cls.basis = SphereBasis(cls.points, 6)

    def test_local_arrow_and_tensor_have_exact_inverses(self):
        p, w = self.points, self.weights
        v = np.array([1.3, -.5, 2.1])
        tensor = np.array([[2., .3, -.4], [.3, -1., .2], [-.4, .2, .5]])
        np.testing.assert_allclose(recover_local_vector(local_vector_response(v, p), p, w), v, atol=1e-12)
        np.testing.assert_allclose(recover_local_tensor(local_tensor_response(tensor, p), p, w), tensor, atol=1e-12)
        arrow = fit(self.basis.scalar, local_vector_response(v, p), w)
        q = fit(self.basis.scalar, local_tensor_response(tensor, p), w)
        self.assertLess(np.max(abs(arrow.coefficients[self.basis.l != 1])), 1e-12)
        self.assertLess(np.max(abs(q.coefficients[~np.isin(self.basis.l, [0, 2])])), 1e-12)
        with self.assertRaises(ValueError):
            local_tensor_response(np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 0]]), p)

    def test_scalar_and_vector_gram(self):
        b, w = self.basis, self.weights
        np.testing.assert_allclose(b.scalar.T @ (w[:, None]*b.scalar), np.eye(49), atol=1e-12)
        v = b.vector.reshape(-1, 96)
        np.testing.assert_allclose(v.T @ (np.repeat(w, 2)[:, None]*v), np.eye(96), atol=1e-12)

    def test_scalar_mean_dipole_and_higher_degrees_recover(self):
        x, y, z = self.points.T
        f = 280 + 2*z + 3*x*z + .2*eval_legendre(6, z)
        result = fit(self.basis.scalar, f, self.weights)
        np.testing.assert_allclose(self.basis.scalar@result.coefficients, f, atol=1e-10)
        self.assertAlmostEqual(result.coefficients[0], 280, places=10)
        self.assertGreater(np.linalg.norm(result.coefficients[self.basis.l == 1]), .1)

    def test_wind_rotation_gradient_and_angular_derivatives(self):
        r, b = self.points, self.basis
        omega, pole = np.array([.2, -.3, .8]), np.array([.4, .1, -.2])
        grad = pole-(r@pole)[:, None]*r + 3*r[:, 2, None]*(np.array([0, 0, 1])-r[:, 2, None]*r)
        wind = b.cartesian_to_tangent(np.cross(omega, r)+grad)
        result = fit(b.vector, wind, self.weights)
        np.testing.assert_allclose(np.einsum("ncp,p->nc", b.vector, result.coefficients), wind, atol=1e-12)
        div, curl = b.wind_channels(result.coefficients)
        np.testing.assert_allclose(b.scalar@div, -2*(r@pole)-6*eval_legendre(2, r[:, 2]), atol=1e-11)
        np.testing.assert_allclose(b.scalar@curl, 2*(r@omega), atol=1e-11)

    def test_kernel_parity_and_original_even_wind_spectrum(self):
        even = kernel_multipliers(6, "even")
        np.testing.assert_allclose(even, [.5, 0, 1/8, 0, -1/48, 0, 1/128], atol=1e-14)
        odd = kernel_multipliers(6, "odd")
        np.testing.assert_array_equal(odd[::2], 0)
        self.assertAlmostEqual(odd[1], 1/8, places=14)
        r, b = self.points, self.basis
        wind = b.cartesian_to_tangent(3*r[:, 2, None]*np.cross(r, [0, 0, 1]))
        result = fit(b.vector, wind, self.weights)
        _, curl = b.wind_channels(result.coefficients)
        np.testing.assert_allclose(response(curl, r, 6, kernel="even"), -.75*eval_legendre(2, r[:, 2]), atol=1e-12)
        # Direct original kernel, integrating separately on the two hemispheres.
        z, w = leggauss(24)
        zz = np.r_[(z+1)/2, -(z+1)/2]
        rr = latlon_points(np.rad2deg(np.arcsin(zz)), np.arange(48)*360/48)
        ww = np.repeat(np.r_[w, w]/(4*48), 48)
        uu = 3*rr[:, 2, None]*np.cross(rr, [0, 0, 1])
        direct = np.sum(ww*np.sign(rr[:, 2])*np.sum(uu*np.cross([0, 0, 1], rr), axis=1))
        self.assertAlmostEqual(direct, -.75, places=12)

    def test_response_rotates_with_the_field(self):
        r, w, b = self.points, self.weights, self.basis
        axis = np.array([1., 2., 3.]); axis /= np.linalg.norm(axis)
        cross = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
        rotation = expm(.7*cross)
        field = lambda p: 2*p[:, 0] + 3*p[:, 0]*p[:, 2] + eval_legendre(4, p[:, 1])
        original = fit(b.scalar, field(r), w).coefficients
        rotated = fit(b.scalar, field(r@rotation), w).coefficients
        for kernel in ("bandlimited", "even", "odd"):
            np.testing.assert_allclose(response(rotated, r, 6, kernel=kernel),
                                       response(original, r@rotation, 6, kernel=kernel), atol=1e-11)

    def test_masked_values_cannot_poison_observed_fit(self):
        b = SphereBasis(self.points, 3)
        f = 2 + self.points[:, 0] + self.points[:, 0]*self.points[:, 2]
        mask = self.points[:, 2] < .4
        poisoned = f.copy(); poisoned[~mask] = 1e100
        missing = f.copy(); missing[~mask] = np.nan
        a = fit(b.scalar, poisoned, self.weights, mask=mask)
        c = fit(b.scalar, missing, self.weights, mask=mask)
        np.testing.assert_array_equal(a.coefficients, c.coefficients)
        np.testing.assert_allclose(b.scalar@a.coefficients, f, atol=1e-10)
        # A zero-filled projection really is a different, biased observation.
        zero = fit(b.scalar, np.where(mask, f, 0), self.weights)
        self.assertGreater(np.linalg.norm(zero.coefficients-a.coefficients), .1)

    def test_rank_deficiency_and_missing_observations_are_explicit(self):
        b = self.basis
        mask = np.arange(len(self.points)) < 3
        with self.assertRaises(ValueError):
            fit(b.scalar, self.points[:, 0], self.weights, mask=mask)
        regularized = fit(b.scalar, self.points[:, 0], self.weights, mask=mask, relative_ridge=1e-6)
        self.assertLessEqual(regularized.diagnostics["unregularized_rank"], 3)
        self.assertIsNone(regularized.diagnostics["unregularized_condition"])
        with self.assertRaises(ValueError):
            fit(b.scalar, np.full(len(self.points), np.nan), self.weights)

    def test_wind_components_share_the_same_valid_domain(self):
        b = self.basis
        wind = b.cartesian_to_tangent(np.cross([0, 0, 1], self.points))
        wind[:20, 1] = np.nan
        a = fit(b.vector, wind, self.weights)
        wind[:20, 0] = 1e100
        c = fit(b.vector, wind, self.weights)
        np.testing.assert_array_equal(a.coefficients, c.coefficients)
        self.assertFalse(a.valid[:20].any())

    def test_transport_preserves_mean_energy_and_correct_phase(self):
        r, w, b = self.points, self.weights, self.basis
        wind = b.cartesian_to_tangent(np.cross([0, 0, 1], r))
        operator = advection_operator(b, wind, w, radius=1)
        np.testing.assert_allclose(operator+operator.T, 0, atol=1e-11)
        initial = 280+3*r[:, 0]+2*(r[:, 0]**2-r[:, 1]**2)
        c = fit(b.scalar, initial, w).coefficients
        time = np.pi/4
        predicted = expm(time*operator)@c
        x0 = np.cos(time)*r[:, 0]+np.sin(time)*r[:, 1]
        y0 = -np.sin(time)*r[:, 0]+np.cos(time)*r[:, 1]
        expected = 280+3*x0+2*(x0*x0-y0*y0)
        np.testing.assert_allclose(b.scalar@predicted, expected, atol=1e-10)
        self.assertAlmostEqual(predicted[0], c[0], places=10)
        self.assertAlmostEqual(np.sum(predicted[1:]**2), np.sum(c[1:]**2), places=10)
        for l in range(1, 7):
            self.assertAlmostEqual(np.sum(predicted[b.l == l]**2), np.sum(c[b.l == l]**2), places=10)
        scaled = advection_operator(b, wind, w, radius=2)
        np.testing.assert_allclose(scaled, operator/2, atol=1e-12)

    def test_even_wind_observation_hides_a_scalar_transport_driver(self):
        r, b, w = self.points, self.basis, self.weights
        wind = b.cartesian_to_tangent(np.cross([0, 0, 1], r))
        c = fit(b.vector, wind, w).coefficients
        _, curl = b.wind_channels(c)
        np.testing.assert_allclose(response(curl, r, 6, kernel="even"), 0, atol=1e-12)
        self.assertGreater(np.max(abs(response(curl, r, 6, kernel="odd"))), .1)
        f = r[:, 0]**2-r[:, 1]**2
        fc = fit(b.scalar, f, w).coefficients
        operator = advection_operator(b, wind, w, radius=1)
        future = b.scalar@(expm(np.pi/4*operator)@fc)
        # Identical initial even wind observations, different future even scalar field.
        self.assertGreater(np.sqrt(np.sum(w*(future-f)**2)), .5)


if __name__ == "__main__":
    unittest.main()
