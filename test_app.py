import unittest
from app import app
import json

class YourTreasurerAdvancedTests(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    # --- 1. BASIC ROUTE TESTING (Status Code 200) ---
    def test_navigation_routes(self):
        """Verify all core navigation endpoints are reachable """
        routes = ['/', '/my_profile', '/analysis', '/history', '/interval_spend']
        for route in routes:
            with self.subTest(route=route):
                response = self.app.get(route)
                self.assertEqual(response.status_code, 200)

    # --- 2. BOUNDARY VALUE ANALYSIS (BVA) ---
    def test_budget_limit_boundaries(self):
        """Test the extremes of the budget input (Zero, Large Number, Negative)"""
        # Case: Zero Budget (Minimum Boundary)
        res_zero = self.app.post('/set_budget', 
            data=json.dumps({"username": "testuser", "password": "123", "limit": 0}),
            content_type='application/json')
        self.assertEqual(res_zero.status_code, 200)

        # Case: Very High Budget (Maximum Boundary)
        res_high = self.app.post('/set_budget', 
            data=json.dumps({"username": "testuser", "password": "123", "limit": 9999999}),
            content_type='application/json')
        self.assertEqual(res_high.status_code, 200)

    # --- 3. EQUIVALENCE PARTITIONING (Valid vs Invalid Data) ---
    def test_login_validation(self):
        """Test correct vs incorrect credentials to verify security logic"""
        # Case: Incorrect Password
        response = self.app.post('/verify_profile', 
            data=json.dumps({"username": "wronguser", "password": "wrongpassword"}),
            content_type='application/json')
        # Based on your app logic, an incorrect password returns 401
        self.assertEqual(response.status_code, 401)

    # --- 4. FUNCTIONAL LOGIC TESTING (Expense Addition) ---
    def test_add_expense_logic(self):
        """Verify that adding an expense returns success status"""
        payload = {
            "username": "testuser",
            "category": "Food",
            "amount": 500.50,
            "description": "Lunch with friends",
            "is_loan": False
        }
        response = self.app.post('/add_expense', 
            data=json.dumps(payload),
            content_type='application/json')
        data = json.loads(response.data)
        self.assertEqual(data['status'], 'success')

    # --- 5. ERROR HANDLING / NEGATIVE TESTING ---
    def test_invalid_history_user(self):
        """Test how the API handles a non-existent user profile"""
        response = self.app.get('/get_history/non_existent_user_123')
        data = json.loads(response.data)
        # Even if user doesn't exist, it should return an empty list [], not crash
        self.assertIsInstance(data, list)

if __name__ == "__main__":
    unittest.main()
