"""Nominal type arguments participate in every unification operation."""
import unittest

from lm.types import INT, STR, Subst, children, nom, substitute, var


class GenericTypes(unittest.TestCase):
    def test_nominal_identity_includes_arguments(self):
        s = Subst()
        a = s.fresh()
        self.assertTrue(s.unify(nom("m.Box", a), nom("m.Box", INT)))
        self.assertEqual(s.resolve(a), INT)
        self.assertFalse(s.unify(nom("m.Box", INT), nom("m.Box", STR)))
        self.assertFalse(s.unify(nom("m.Box", INT), nom("m.Other", INT)))
        self.assertFalse(s.unify(nom("m.Box", INT), nom("m.Box")))

    def test_occurs_check_sees_nominal_arguments(self):
        s = Subst()
        a = s.fresh()
        self.assertFalse(s.unify(a, nom("m.Tree", a)))

    def test_instantiation_preserves_shared_arguments_and_freshens_uses(self):
        s = Subst()
        template = nom("m.Assoc", var("a"), var("a"))
        first, second = s.inst(template, {}), s.inst(template, {})
        self.assertEqual(first[2], first[3])
        self.assertNotEqual(first[2], second[2])
        self.assertEqual(children(first), first[2:])

    def test_substitution_and_diagnostic_printing_keep_rigid_variables(self):
        t = nom("m.Tree", var("a"))
        self.assertEqual(substitute(t, {"a": var("b")}), nom("m.Tree", var("b")))
        self.assertEqual(Subst().show(t), "(m.Tree a)")
        self.assertEqual(Subst().show(substitute(t, {"a": INT})), "(m.Tree Int)")
