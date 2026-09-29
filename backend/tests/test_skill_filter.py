"""
Unit tests for skill filtering and demand weight calculation.

Covers:
  - is_plausible_skill_name: rejects seniority descriptors, culture words, soft skills, noise
  - filter_technical_skills_only: strips soft skills, preserves order
  - _synthetic_demand_pcts: harmonic decay, no flat equal distribution
"""
import pytest

from app.services.skill_service import (
    filter_technical_skills_only,
    is_plausible_skill_name,
)
from app.services.match_service import _synthetic_demand_pcts


# ---------------------------------------------------------------------------
# is_plausible_skill_name
# ---------------------------------------------------------------------------

class TestIsPlausibleSkillName:
    # --- Newly-added guards (bugs reported) ---

    def test_rejects_culture_word_camaraderie(self):
        """'camaraderie' is a personality/culture word, not a technical skill."""
        assert is_plausible_skill_name("camaraderie") is False

    def test_rejects_seniority_phrase(self):
        """'agile seniority level' contains a seniority descriptor and must be rejected."""
        assert is_plausible_skill_name("agile seniority level") is False

    def test_rejects_bare_seniority_word(self):
        assert is_plausible_skill_name("seniority") is False

    def test_rejects_mid_level(self):
        assert is_plausible_skill_name("mid-level") is False

    def test_rejects_culture_word_passion(self):
        assert is_plausible_skill_name("passion") is False

    def test_rejects_culture_word_guru(self):
        assert is_plausible_skill_name("guru") is False

    # --- Existing correct behaviour must not regress ---

    def test_accepts_python(self):
        assert is_plausible_skill_name("python") is True

    def test_accepts_machine_learning(self):
        assert is_plausible_skill_name("machine learning") is True

    def test_accepts_docker(self):
        assert is_plausible_skill_name("docker") is True

    def test_accepts_aws(self):
        assert is_plausible_skill_name("aws") is True

    def test_rejects_soft_skill_leadership(self):
        assert is_plausible_skill_name("leadership") is False

    def test_rejects_soft_skill_teamwork(self):
        assert is_plausible_skill_name("teamwork") is False

    def test_rejects_blocklisted_linkedin(self):
        assert is_plausible_skill_name("linkedin") is False

    def test_rejects_long_sentence_fragment(self):
        assert is_plausible_skill_name("help accelerate careers across all industries") is False

    # --- New tests: sentence fragments, industry nouns, over-length phrases ---

    def test_rejects_jd_fragment_with_stay(self):
        """'optimizing performance stay' — 'stay' is a JD stop-word, not a skill component."""
        assert is_plausible_skill_name("optimizing performance stay") is False

    def test_rejects_jd_fragment_with_understanding(self):
        """'prediction understanding financial' — 'understanding' disqualifies the phrase."""
        assert is_plausible_skill_name("prediction understanding financial") is False

    def test_rejects_jd_fragment_productionalization(self):
        """'roadmaps productionalization' — both words are process nouns, not a learnable skill."""
        assert is_plausible_skill_name("roadmaps productionalization") is False

    def test_rejects_single_industry_noun_insurance(self):
        """'insurance' is an industry sector, not a learnable technical skill."""
        assert is_plausible_skill_name("insurance") is False

    def test_rejects_single_industry_noun_opportunities(self):
        """'opportunities' is a JD filler word, not a skill."""
        assert is_plausible_skill_name("opportunities") is False

    def test_rejects_phrase_over_three_words(self):
        """Phrases with more than 3 words are always sentence fragments."""
        assert is_plausible_skill_name("prediction understanding financial modeling") is False

    def test_legit_skill_not_broken_by_new_filters(self):
        """Ensure new filters don't regress common multi-word technical skills."""
        assert is_plausible_skill_name("machine learning") is True
        assert is_plausible_skill_name("feature engineering") is True
        assert is_plausible_skill_name("data visualization") is True


# ---------------------------------------------------------------------------
# filter_technical_skills_only
# ---------------------------------------------------------------------------

class TestFilterTechnicalSkillsOnly:
    def test_removes_soft_skills(self):
        skills = ["python", "communication", "docker", "teamwork"]
        result = filter_technical_skills_only(skills)
        assert "communication" not in result
        assert "teamwork" not in result
        assert "python" in result
        assert "docker" in result

    def test_preserves_relative_order(self):
        skills = ["kubernetes", "aws", "terraform"]
        result = filter_technical_skills_only(skills)
        assert result == ["kubernetes", "aws", "terraform"]

    def test_deduplicates(self):
        skills = ["python", "Python", "PYTHON"]
        result = filter_technical_skills_only(skills)
        # All three normalise to the same key; only first kept
        assert len(result) == 1

    def test_empty_input(self):
        assert filter_technical_skills_only([]) == []


# ---------------------------------------------------------------------------
# _synthetic_demand_pcts  (demand weight bug)
# ---------------------------------------------------------------------------

class TestSyntheticDemandPcts:
    def test_five_skills_not_flat_20_percent(self):
        """The bug: 5 skills all showing 20%. Weights must differ."""
        pcts = _synthetic_demand_pcts(5)
        assert len(pcts) == 5
        assert len(set(pcts)) > 1, "All weights are equal — flat 1/n bug is still present"

    def test_weights_sum_to_100(self):
        for n in [1, 3, 5, 10]:
            total = sum(_synthetic_demand_pcts(n))
            assert abs(total - 100.0) < 0.5, f"Weights don't sum to ~100 for n={n}"

    def test_weights_are_strictly_descending(self):
        """Rank-0 skill should have the highest demand weight."""
        pcts = _synthetic_demand_pcts(5)
        assert pcts == sorted(pcts, reverse=True), "Weights are not in descending order"

    def test_single_skill_nonzero(self):
        pcts = _synthetic_demand_pcts(1)
        assert len(pcts) == 1
        assert pcts[0] > 0

    def test_empty_input_returns_empty(self):
        assert _synthetic_demand_pcts(0) == []

    def test_top_skill_has_higher_weight_than_last(self):
        pcts = _synthetic_demand_pcts(5)
        assert pcts[0] > pcts[-1], "Top-ranked skill should weigh more than bottom-ranked"
