# Scientific open-problems graph: cross-problem pilot R02 (2026-11-09)

Status: **research hypothesis / known-physics toy constraints only**. No new physical law or observational confirmation is claimed. Companion to the local Noosphere open-problems graph R01 (34 problems, 19 shared mechanisms, 151 initial links; R02 adds four hypothesis nodes and 11 links).

## Strongest intersection: neutrino mass, baryon asymmetry and asymmetric dark matter

The common-cogenesis idea has published precedents, including Phys. Rev. D **114, 095012 (2026-11-05)** and *PTEP* **2026, 013B08**. Shared mathematical constraints do **not** prove common physical origin.

Using Planck 2018 base-ΛCDM \(\Omega_ch^2=0.120\pm0.001\) and \(\Omega_bh^2=0.0224\pm0.0001\),

\[
R=\frac{\Omega_c}{\Omega_b}\approx 5.357, \qquad
m_\chi=R\,m_p\,\frac{f_\chi}{r}.
\]

Here \(r=Y_{\chi,\mathrm{asym}}/Y_B\) is the ratio of surviving conserved-number asymmetries and \(f_\chi=Y_{\chi,\mathrm{asym}}/Y_{\chi,\mathrm{total}}\) is the relic asymmetry fraction. Conditional benchmarks: \(m_\chi\approx5.026\) GeV if \(r=f_\chi=1\); alternatively \(1.782\) GeV if \(f_\chi=1\) and the dark asymmetry equals the initial B-L asymmetry, so \(r=79/28\) after sphaleron conversion. These are not universal predictions.

## Hierarchical type-I leptogenesis bound

With \(v=174\) GeV, \(\Delta m_\nu=0.05\) eV, \(\kappa=0.1\), \(g_*=106.75\), and \(\eta_B=6.120\times10^{-10}\) (2026 helium + BBN + CMB), the simple one-flavour approximation

\[
|\varepsilon_1|\le\frac{3M_1\Delta m_\nu}{16\pi v^2}, \quad
Y_B\simeq \frac{28}{79}\frac{\kappa\varepsilon_1}{g_*}, \quad
Y_B=\eta_B/7.04
\]

implies \(M_1\gtrsim2.656\times10^9\) GeV for the assumed maximum CP asymmetry. A 1 TeV **hierarchical** benchmark underproduces the observed \(Y_B\) by \(\approx2.66\times10^6\). This **does not** exclude near-degenerate, flavour-aware or time-dependent-CP alternatives.

The 2026 near-resonant study JHEP 06 (2026) 214 reports \(\varepsilon\le1/200\) in its controlled quasi-degenerate regime and viable models at much lower masses; it is a separate model family from spontaneous-majoron cogenesis.

## Second intersection: Hubble tension and supernova catalog calibration

arXiv:2610.23657 (2026-10-16) finds a sample-dependent Hubble inference and reports an illustrative relative absolute-magnitude shift \(\Delta M=0.0646\) mag. A **pure scaling** gives \(10^{\Delta M/5}=1.0302\); fitting an actual cosmological model requires all calibration and covariance terms. No resolution is claimed.

## Next falsification requirements

- Derive the asymmetry ratio \(r\) and relic fraction \(f_\chi\) *independently* from one specified Lagrangian, not by tuning them to 5 GeV.
- Solve flavour-aware kinetic equations, symmetric annihilation/freeze-out and cosmological observables simultaneously.
- Compare a predicted dark mass **and interaction cross section** with experiment; document null results.
- Keep observation dates separate from record dates and label hypotheses as unconfirmed.

## Sources

- [Planck 2018 cosmological parameters](https://arxiv.org/abs/1807.06209)
- [2026 spontaneous leptogenesis and asymmetric dark matter](https://doi.org/10.1103/jvw4-pdg1)
- [2026 common origin of Dirac neutrino mass / ADM / BAU](https://academic.oup.com/ptep/article/2026/1/013B08/8405680)
- [2026 LBT primordial helium + baryon asymmetry](https://doi.org/10.3847/1538-4357/ae879c)
- [Davidson–Ibarra bound and extensions](https://pmc.ncbi.nlm.nih.gov/articles/PMC12078409/)
- [Near-resonant thermal leptogenesis (2026)](https://doi.org/10.1007/JHEP06(2026)214)
- [SN catalogue comparison (2026)](https://arxiv.org/abs/2610.23657)

Reproduce elementary arithmetic with `reproduce.py`; this is **not** a Boltzmann solver or a new theory.
