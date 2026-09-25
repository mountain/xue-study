"""Typed spherical response functions and finite real-harmonic coordinates.

The physical position r and the observation direction a are separate arguments.
Finite coefficients are storage coordinates for a response on the whole sphere.
All surface differential operators below refer to a unit sphere, unless radius
is explicitly supplied. Wind components are local east/north, not Cartesian x/y.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import numpy as np
from numpy.polynomial.legendre import leggauss
from scipy.special import eval_legendre, sph_harm_y


def unit_points(points):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError("Expected finite N x 3 unit vectors")
    if not np.allclose(np.linalg.norm(points, axis=1), 1, rtol=0, atol=1e-10):
        raise ValueError("Directions must be unit vectors")
    return points


def latlon_points(lat, lon):
    latitude, longitude = np.meshgrid(np.deg2rad(lat), np.deg2rad(lon), indexing="ij")
    return np.stack([np.cos(latitude)*np.cos(longitude),
                     np.cos(latitude)*np.sin(longitude), np.sin(latitude)], axis=-1).reshape(-1, 3)


def gaussian_grid(nlat=24, nlon=48):
    z, w = leggauss(nlat)
    points = latlon_points(np.rad2deg(np.arcsin(z)), np.arange(nlon)*360/nlon)
    weights = np.repeat(w/(2*nlon), nlon)
    return points, weights


def local_vector_response(vector, axes):
    vector = np.asarray(vector, dtype=float)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ValueError("Expected one finite Cartesian vector")
    return unit_points(axes) @ vector


def recover_local_vector(response, axes, weights):
    """Requires a full-sphere quadrature exact for degree two, not a masked view."""
    return 3 * (unit_points(axes).T @ (np.asarray(weights)*response))


def local_tensor_response(tensor, axes):
    """Symmetric rank-two tensor; its trace contributes degree zero."""
    tensor = np.asarray(tensor, dtype=float)
    if tensor.shape != (3, 3) or not np.isfinite(tensor).all() or not np.allclose(tensor, tensor.T):
        raise ValueError("Expected one finite symmetric 3 x 3 tensor")
    axes = unit_points(axes)
    return np.einsum("ni,ij,nj->n", axes, tensor, axes)


def recover_local_tensor(response, axes, weights):
    """Full-sphere quadrature exact for degree four. Antisymmetric tensors are excluded."""
    axes = unit_points(axes)
    weighted = np.asarray(weights)*response
    return 7.5*np.einsum("n,ni,nj->ij", weighted, axes, axes) - 1.5*weighted.sum()*np.eye(3)


def real_harmonics(points, degree, *, derivatives=False):
    points = unit_points(points)
    if not isinstance(degree, int) or degree < 0:
        raise ValueError("degree must be a nonnegative integer")
    theta = np.arccos(np.clip(points[:, 2], -1, 1))
    phi = np.mod(np.arctan2(points[:, 1], points[:, 0]), 2*np.pi)
    if derivatives and np.any(np.sin(theta) < 1e-10):
        raise ValueError("East/north components need nonpolar grid points; omit exact poles")
    values, gradients, labels = [], [], []
    for l in range(degree+1):
        for m in range(l+1):
            if derivatives:
                y, dy = sph_harm_y(l, m, theta, phi, diff_n=1)
            else:
                y = sph_harm_y(l, m, theta, phi)
            for phase in (["real"] if m == 0 else ["real", "imag"]):
                scale = np.sqrt(4*np.pi) * (1 if m == 0 else np.sqrt(2))
                values.append(getattr(y, phase)*scale)
                labels.append({"l": l, "m": m, "phase": phase})
                if derivatives:
                    gradients.append(np.stack([getattr(dy[:, 1], phase)/np.sin(theta),
                                               -getattr(dy[:, 0], phase)], axis=1)*scale)
    return np.stack(values, axis=1), (np.stack(gradients, axis=2) if derivatives else None), labels


class SphereBasis:
    def __init__(self, points, degree):
        self.points = unit_points(points)
        self.degree = degree
        self.scalar, self.gradient, self.scalar_labels = real_harmonics(points, degree, derivatives=True)
        self.l = np.array([label["l"] for label in self.scalar_labels])

    @cached_property
    def vector(self):
        grad = self.gradient[:, :, 1:] / np.sqrt(self.l[1:]*(self.l[1:]+1))
        # r cross gradient: east=-gradient_north, north=gradient_east.
        rot = np.stack([-grad[:, 1, :], grad[:, 0, :]], axis=1)
        return np.concatenate([grad, rot], axis=2)

    @property
    def vector_labels(self):
        return [{**label, "family": family} for family in ("gradient", "rotation")
                for label in self.scalar_labels[1:]]

    def cartesian_to_tangent(self, vector):
        vector = np.asarray(vector)
        if vector.shape != self.points.shape:
            raise ValueError("Cartesian vectors must match the position grid")
        lon = np.arctan2(self.points[:, 1], self.points[:, 0])
        z, c = self.points[:, 2], np.linalg.norm(self.points[:, :2], axis=1)
        east = np.stack([-np.sin(lon), np.cos(lon), np.zeros_like(z)], axis=1)
        north = np.stack([-z*np.cos(lon), -z*np.sin(lon), c], axis=1)
        return np.stack([np.sum(vector*east, axis=1), np.sum(vector*north, axis=1)], axis=1)

    def wind_channels(self, coefficients):
        """Angular divergence and radial curl: physical s^-1 needs division by radius."""
        n = len(self.l)-1
        coefficients = np.asarray(coefficients)
        if coefficients.shape != (2*n,):
            raise ValueError("Incorrect vector coefficient count")
        scale = -np.sqrt(self.l[1:]*(self.l[1:]+1))
        return (np.r_[0., scale*coefficients[:n]], np.r_[0., scale*coefficients[n:]])


@dataclass
class Fit:
    coefficients: np.ndarray
    gram: np.ndarray
    valid: np.ndarray
    diagnostics: dict


def fit(basis, values, weights, *, mask=None, relative_ridge=0., rank_tolerance=1e-10):
    """Scalar (N,P) or tangent-vector (N,2,P) weighted fit over observed points.

    Every wind point uses one shared mask for both components. Invalid values are
    removed before matrix arithmetic, so NaNs and poisoned unobserved cells cannot
    leak into coefficients. A masked solution is an extension, not measured truth
    outside its domain. The unregularized domain Gram is returned for downstream use.
    """
    basis, values, weights = np.asarray(basis), np.asarray(values), np.asarray(weights)
    if basis.ndim not in (2, 3) or values.shape != basis.shape[:-1] or weights.shape != (len(basis),):
        raise ValueError("Basis, field and area weight shapes do not agree")
    if not np.isfinite(basis).all() or not np.isfinite(weights).all() or np.any(weights < 0) or weights.sum() <= 0:
        raise ValueError("Invalid basis or area weights")
    if not np.isfinite(relative_ridge) or relative_ridge < 0 or not 0 < rank_tolerance < 1:
        raise ValueError("Invalid regularization/rank settings")
    valid = np.isfinite(values) if values.ndim == 1 else np.isfinite(values).all(axis=1)
    valid &= weights > 0
    if mask is not None:
        if np.asarray(mask).dtype != bool or np.shape(mask) != valid.shape:
            raise ValueError("Mask must be a Boolean vector matching the grid")
        valid &= mask
    if not valid.any():
        raise ValueError("No observed points")
    coverage = float(weights[valid].sum()/weights.sum())
    w = weights[valid]/weights[valid].sum()
    if basis.ndim == 3:
        w = np.repeat(w, basis.shape[1])
    matrix = basis[valid].reshape(-1, basis.shape[-1])
    observed = values[valid].reshape(-1)
    gram = matrix.T @ (w[:, None]*matrix)
    rhs = matrix.T @ (w*observed)
    eigenvalues = np.linalg.eigvalsh(gram)
    rank = int(np.sum(eigenvalues > eigenvalues[-1]*rank_tolerance))
    penalty = float(relative_ridge*np.trace(gram)/len(gram))
    if rank < len(gram) and penalty == 0:
        raise ValueError("Observation geometry does not identify the retained coefficients")
    coefficients = np.linalg.solve(gram+penalty*np.eye(len(gram)), rhs)
    residual = matrix@coefficients-observed
    mse = float(np.sum(w*residual**2))
    condition = float(eigenvalues[-1]/eigenvalues[0]) if eigenvalues[0] > eigenvalues[-1]*rank_tolerance else None
    return Fit(coefficients, gram, valid, {
        "coefficients": len(gram), "observed_points": int(valid.sum()), "area_fraction": coverage,
        "unregularized_rank": rank, "unregularized_condition": condition,
        "smallest_gram_eigenvalue": float(eigenvalues[0]), "largest_gram_eigenvalue": float(eigenvalues[-1]),
        "relative_ridge": relative_ridge, "ridge": penalty, "observed_domain_rmse": float(np.sqrt(mse)),
        "interpretation": "weighted in-sample representation; not forecast skill",
    })


def kernel_multipliers(degree, kernel):
    if kernel == "bandlimited":
        return np.ones(degree+1)
    if kernel not in {"even", "odd"}:
        raise ValueError("Unknown kernel")
    # Integrate polynomial halves exactly to quadrature accuracy; enforce parity
    # algebraically instead of integrating across the absolute-value cusp.
    z, w = leggauss(max(16, (degree+5)//2))
    x, w = (z+1)/2, w/2
    return np.array([
        float(np.sum(w*x*eval_legendre(l, x))) if kernel == "even" and l % 2 == 0 else
        float(np.sum(w*x*x*eval_legendre(l, x))/2) if kernel == "odd" and l % 2 == 1 else 0.
        for l in range(degree+1)])


def response(coefficients, axes, degree, *, kernel="bandlimited"):
    values, _, labels = real_harmonics(axes, degree)
    coefficients = np.asarray(coefficients)
    if coefficients.shape != (len(labels),):
        raise ValueError("Incorrect scalar coefficient count")
    beta = kernel_multipliers(degree, kernel)
    return values @ (coefficients*beta[[label["l"] for label in labels]])


def advection_operator(basis: SphereBasis, wind, weights, *, radius):
    """Galerkin df/dt=-u.grad(f) for prescribed wind on a complete sphere.

    No scalar-to-wind feedback, no thermodynamics. The caller must supply a full
    quadrature and radius/time/velocity units that agree. This does not silently
    close an incomplete observed domain or restore discarded spatial modes.
    """
    wind, weights = np.asarray(wind), np.asarray(weights)
    if wind.shape != (len(basis.points), 2) or weights.shape != (len(basis.points),):
        raise ValueError("Wind/weights do not match the basis")
    if not np.isfinite(wind).all() or not np.isfinite(weights).all() or np.any(weights <= 0) or not np.isfinite(radius) or radius <= 0:
        raise ValueError("Complete finite wind, positive weights and radius required")
    weights = weights/weights.sum()
    transport = np.einsum("nc,ncp->np", wind, basis.gradient)/radius
    gram = basis.scalar.T @ (weights[:, None]*basis.scalar)
    return np.linalg.solve(gram, -basis.scalar.T @ (weights[:, None]*transport))
