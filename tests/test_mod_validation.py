import unittest
from mod_validation import normalize_mod_entry
from armahq_compare import normalize_remote_mods


class ModValidationTests(unittest.TestCase):
    def test_canonical_values_and_optional_fields(self):
        self.assertEqual(normalize_mod_entry({'modId':' aabb ', 'name':' Test ', 'version':' 1.2 '}),
                         {'modId':'AABB', 'name':'Test', 'version':'1.2'})
        self.assertEqual(normalize_mod_entry({'modId':'AABB'}), {'modId':'AABB'})

    def test_remote_and_local_paths_reject_the_same_invalid_fields(self):
        for field, value in [('name','x'*201), ('name','bad\nname'), ('version','1 2'),
                             ('version','1"2'), ('version','1\\2'), ('name',123),
                             ('version',False), ('modId',123), ('name','bad\x7fname')]:
            with self.subTest(field=field, value=value):
                entry = {'modId':'AABB', field:value}
                self.assertIsNone(normalize_mod_entry(entry))
                with self.assertRaises(ValueError):
                    normalize_remote_mods([entry])
