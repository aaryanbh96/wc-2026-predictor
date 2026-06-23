#!/usr/bin/env python3
"""
Python mirror of the in-page rating + recent-form model.

This MUST stay numerically identical to the JavaScript in index.html so that the
predictions the GitHub Action freezes into results.json match what the page would
have shown. If you change the model in the page, change it here too. The constants
and formulas below are copied directly from the page.
"""

K_BASE = 30
HOME_ADV = 60
FORM_CAP = 140
FORM_SCALE = 4.2

# 48-team seed: (name, group, rating) — identical to SEED in index.html
SEED = [
    ("Mexico", "A", 1906), ("Korea Republic", "A", 1856), ("Czechia", "A", 1760), ("South Africa", "A", 1745),
    ("Canada", "B", 1816), ("Switzerland", "B", 1886), ("Bosnia and Herzegovina", "B", 1770), ("Qatar", "B", 1742),
    ("Brazil", "C", 2040), ("Morocco", "C", 1932), ("Scotland", "C", 1775), ("Haiti", "C", 1660),
    ("USA", "D", 1912), ("Paraguay", "D", 1782), ("Australia", "D", 1842), ("Türkiye", "D", 1790),
    ("Germany", "E", 1980), ("Ecuador", "E", 1862), ("Côte d'Ivoire", "E", 1798), ("Curaçao", "E", 1680),
    ("Netherlands", "F", 2000), ("Japan", "F", 1902), ("Sweden", "F", 1800), ("Tunisia", "F", 1778),
    ("Egypt", "G", 1820), ("Belgium", "G", 1985), ("IR Iran", "G", 1768), ("New Zealand", "G", 1660),
    ("Spain", "H", 2070), ("Uruguay", "H", 1948), ("Cabo Verde", "H", 1700), ("Saudi Arabia", "H", 1772),
    ("France", "I", 2085), ("Norway", "I", 1794), ("Senegal", "I", 1892), ("Iraq", "I", 1710),
    ("Argentina", "J", 2110), ("Austria", "J", 1850), ("Algeria", "J", 1764), ("Jordan", "J", 1700),
    ("Colombia", "K", 1938), ("Congo DR", "K", 1730), ("Portugal", "K", 2015), ("Uzbekistan", "K", 1716),
    ("England", "L", 2045), ("Ghana", "L", 1802), ("Panama", "L", 1722), ("Croatia", "L", 1952),
]

# Round-1 results baked into the page's seed — replayed first to reach the same start state.
SEED_RESULTS = [
    ("Canada", 6, 0, "Qatar"), ("Mexico", 1, 0, "Korea Republic"), ("USA", 2, 0, "Australia"),
    ("Algeria", 0, 3, "Argentina"), ("Argentina", 2, 0, "Austria"), ("Belgium", 0, 0, "IR Iran"),
    ("Bosnia and Herzegovina", 1, 4, "Switzerland"), ("Brazil", 3, 0, "Haiti"), ("Cabo Verde", 2, 2, "Uruguay"),
    ("Colombia", 3, 1, "Uzbekistan"), ("Congo DR", 1, 1, "Portugal"), ("Côte d'Ivoire", 1, 2, "Germany"),
    ("Croatia", 2, 4, "England"), ("Curaçao", 0, 0, "Ecuador"), ("Czechia", 1, 1, "South Africa"),
    ("Egypt", 3, 1, "New Zealand"), ("France", 3, 1, "Senegal"), ("Ghana", 1, 0, "Panama"),
    ("Iraq", 1, 4, "Norway"), ("Japan", 4, 0, "Tunisia"), ("Jordan", 1, 3, "Austria"),
    ("Morocco", 1, 0, "Scotland"), ("Netherlands", 5, 1, "Sweden"), ("Paraguay", 1, 0, "Türkiye"),
    ("Saudi Arabia", 0, 4, "Spain"),
]


class Model:
    def __init__(self):
        self.rating = {n: r for n, g, r in SEED}
        self.hist = {n: [] for n, g, r in SEED}
        self._seed_sigs = set()
        for a, ga, gb, b in SEED_RESULTS:
            self._seed_sigs.add(self._sig(a, ga, gb, b))
            self.learn(a, ga, gb, b)

    @staticmethod
    def _sig(a, ga, gb, b):
        return "|".join(sorted([f"{a}:{ga}", f"{b}:{gb}"]))

    def is_seed(self, a, ga, gb, b):
        return self._sig(a, ga, gb, b) in self._seed_sigs

    def raw_expect(self, a, b):
        return 1 / (1 + 10 ** ((self.rating[b] - self.rating[a]) / 400))

    def form_nudge(self, team):
        h = self.hist.get(team) or []
        games = h[-5:]
        n = len(games)
        if n == 0:
            return 0.0
        num = den = 0.0
        for i, g in enumerate(games):
            opp = g["opp"]
            if opp not in self.rating:
                continue
            from_end = n - 1 - i
            w = 1.0 if from_end >= 3 else (2.2 - 0.4 * from_end)
            eA = self.raw_expect(team, opp)
            gf, ga = g["gf"], g["ga"]
            sA = 1.0 if gf > ga else (0.0 if gf < ga else 0.5)
            surprise = sA - eA
            inf = 1 - (2 * abs(eA - 0.5)) ** 1.5
            margin = abs(gf - ga)
            if gf > ga:
                contrib = surprise * (1 + 0.10 * min(3, margin)) * inf
            elif gf < ga:
                base = surprise * (1 + 0.30 * min(4, margin))
                contrib = base * (0.55 * inf + 0.45)
            else:
                contrib = surprise * inf
            num += w * contrib
            den += w
        f = num / den if den else 0.0
        sample = min(1.0, n / 3.0)
        return max(-FORM_CAP, min(FORM_CAP, f * FORM_CAP * FORM_SCALE * sample))

    def eff_rating(self, n):
        return self.rating[n] + self.form_nudge(n)

    def predict(self, a, b, neutral=True):
        """Return (pA, pD, pB) win/draw/win probabilities, form-adjusted."""
        if a not in self.rating or b not in self.rating:
            return None
        adj = 0 if neutral else HOME_ADV
        eA = 1 / (1 + 10 ** ((self.eff_rating(b) - (self.eff_rating(a) + adj)) / 400))
        drawW = 0.27 * (1 - abs(eA - 0.5) * 1.4)
        return (eA * (1 - drawW), drawW, (1 - eA) * (1 - drawW))

    def learn(self, a, ga, gb, b, neutral=True, stage_w=1.0):
        if a not in self.rating or b not in self.rating:
            return
        eA = 1 / (1 + 10 ** ((self.rating[b] - (self.rating[a] + (0 if neutral else HOME_ADV))) / 400))
        sA = 1.0 if ga > gb else (0.0 if ga < gb else 0.5)
        margin = abs(ga - gb)
        m_mult = 1 if margin <= 1 else (1.5 if margin == 2 else (11 + margin) / 8)
        K = K_BASE * m_mult * stage_w
        delta = K * (sA - eA)
        self.rating[a] += delta
        self.rating[b] -= delta
        self.hist.setdefault(a, []).append({"opp": b, "gf": ga, "ga": gb})
        self.hist.setdefault(b, []).append({"opp": a, "gf": gb, "ga": ga})
        if len(self.hist[a]) > 8:
            self.hist[a] = self.hist[a][-8:]
        if len(self.hist[b]) > 8:
            self.hist[b] = self.hist[b][-8:]
