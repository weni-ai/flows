"""
Tests to investigate datetime handling differences between API and direct SDK calls.

Run with: python manage.py test temba.api.v2.services.tests.test_events_datetime -v 2
Or with pytest: pytest temba/api/v2/services/tests/test_events_datetime.py -v -s
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from rest_framework import serializers


class EventFilterSerializerTest(serializers.Serializer):
    """Replica of the EventFilterSerializer for testing"""

    date_start = serializers.DateTimeField(required=True)
    date_end = serializers.DateTimeField(required=True)
    key = serializers.CharField(required=False)
    event_name = serializers.CharField(required=False)
    limit = serializers.IntegerField(required=False)
    offset = serializers.IntegerField(required=False)


def normalize_datetime_params_original(params):
    """Original implementation for comparison"""
    if "date_start" in params and hasattr(params["date_start"], "isoformat"):
        dt_start = params["date_start"]
        if dt_start.tzinfo is not None:
            dt_start = dt_start.astimezone(timezone.utc)
        start_str = dt_start.isoformat()
        if start_str.endswith("+00:00"):
            start_str = start_str.replace("+00:00", "Z")
        params["date_start"] = start_str

    if "date_end" in params and hasattr(params["date_end"], "isoformat"):
        dt_end = params["date_end"]
        if dt_end.tzinfo is not None:
            dt_end = dt_end.astimezone(timezone.utc)
        end_str = dt_end.isoformat()
        if end_str.endswith("+00:00"):
            end_str = end_str.replace("+00:00", "Z")
        params["date_end"] = end_str

    return params


class EventsDatetimeInvestigationTest(TestCase):
    """
    Tests to investigate the datetime handling difference between
    API calls and direct SDK calls.
    """

    def test_drf_datetime_field_with_different_formats(self):
        """
        Test how DRF DateTimeField parses different date formats.
        This shows what the API receives after serializer validation.
        """
        print("\n" + "=" * 80)
        print("TEST: DRF DateTimeField parsing with different date formats")
        print("=" * 80)

        test_cases = [
            # Format used in the script (no timezone)
            {"date_start": "2026-01-26T03:00:00", "date_end": "2026-01-27T02:59:59"},
            # Format with Z suffix
            {"date_start": "2026-01-26T03:00:00Z", "date_end": "2026-01-27T02:59:59Z"},
            # Format with explicit +00:00
            {"date_start": "2026-01-26T03:00:00+00:00", "date_end": "2026-01-27T02:59:59+00:00"},
            # Format with different timezone
            {"date_start": "2026-01-26T03:00:00-03:00", "date_end": "2026-01-27T02:59:59-03:00"},
        ]

        for i, input_data in enumerate(test_cases, 1):
            print(f"\n--- Case {i}: Input ---")
            print(f"  date_start: {input_data['date_start']}")
            print(f"  date_end: {input_data['date_end']}")

            serializer = EventFilterSerializerTest(data=input_data)
            if serializer.is_valid():
                validated = serializer.validated_data
                ds = validated["date_start"]
                de = validated["date_end"]

                print(f"\n--- Case {i}: After DRF DateTimeField ---")
                print(f"  date_start: {ds}")
                print(f"    type: {type(ds).__name__}")
                print(f"    tzinfo: {ds.tzinfo}")
                print(f"    is naive: {ds.tzinfo is None}")

                print(f"  date_end: {de}")
                print(f"    type: {type(de).__name__}")
                print(f"    tzinfo: {de.tzinfo}")
                print(f"    is naive: {de.tzinfo is None}")
            else:
                print(f"  VALIDATION ERROR: {serializer.errors}")

    def test_normalize_datetime_params_behavior(self):
        """
        Test what _normalize_datetime_params does with naive vs aware datetimes.
        This is the critical function that may be causing the discrepancy.
        """
        print("\n" + "=" * 80)
        print("TEST: _normalize_datetime_params behavior")
        print("=" * 80)

        # Case 1: Naive datetime (no timezone)
        print("\n--- Case 1: Naive datetime (no timezone) ---")
        naive_dt = datetime(2026, 1, 26, 3, 0, 0)
        params1 = {"date_start": naive_dt, "date_end": datetime(2026, 1, 27, 2, 59, 59)}
        print(f"  BEFORE: date_start={params1['date_start']}, tzinfo={params1['date_start'].tzinfo}")
        normalize_datetime_params_original(params1)
        print(f"  AFTER:  date_start={params1['date_start']}")
        print(f"  Has 'Z' suffix: {'Z' in str(params1['date_start'])}")

        # Case 2: Aware datetime with UTC
        print("\n--- Case 2: Aware datetime with UTC ---")
        aware_utc = datetime(2026, 1, 26, 3, 0, 0, tzinfo=timezone.utc)
        params2 = {"date_start": aware_utc, "date_end": datetime(2026, 1, 27, 2, 59, 59, tzinfo=timezone.utc)}
        print(f"  BEFORE: date_start={params2['date_start']}, tzinfo={params2['date_start'].tzinfo}")
        normalize_datetime_params_original(params2)
        print(f"  AFTER:  date_start={params2['date_start']}")
        print(f"  Has 'Z' suffix: {'Z' in str(params2['date_start'])}")

        # Case 3: String (like direct SDK call)
        print("\n--- Case 3: String (direct SDK call) ---")
        params3 = {"date_start": "2026-01-26T03:00:00", "date_end": "2026-01-27T02:59:59"}
        print(f"  BEFORE: date_start={params3['date_start']}, type={type(params3['date_start']).__name__}")
        normalize_datetime_params_original(params3)
        print(f"  AFTER:  date_start={params3['date_start']}")
        print(f"  (String unchanged because no 'isoformat' method)")

    def test_full_api_flow_simulation(self):
        """
        Simulate the full API flow from request to datalake params.
        """
        print("\n" + "=" * 80)
        print("TEST: Full API flow simulation")
        print("=" * 80)

        # Simulate what the script sends
        raw_params = {
            "date_start": "2026-01-26T03:00:00",
            "date_end": "2026-01-27T02:59:59",
            "event_name": "weni_nexus_data",
            "key": "conversation_classification",
            "limit": "1000",
            "offset": "0",
        }

        print("\n--- Step 1: Raw request params (what script sends) ---")
        for k, v in raw_params.items():
            print(f"  {k}: {v} (type: {type(v).__name__})")

        # DRF serializer validation
        serializer = EventFilterSerializerTest(data=raw_params)
        serializer.is_valid(raise_exception=True)
        validated = dict(serializer.validated_data)

        print("\n--- Step 2: After DRF serializer validation ---")
        for k, v in validated.items():
            extra = ""
            if hasattr(v, "tzinfo"):
                extra = f", tzinfo={v.tzinfo}"
            print(f"  {k}: {v} (type: {type(v).__name__}{extra})")

        # Normalize datetime params (what happens in _prepare_datalake_params)
        normalize_datetime_params_original(validated)

        print("\n--- Step 3: After _normalize_datetime_params (sent to datalake) ---")
        for k, v in validated.items():
            print(f"  {k}: {v} (type: {type(v).__name__})")

        # Compare with direct SDK call
        print("\n--- Comparison: Direct SDK call (string) ---")
        direct_sdk_params = {
            "date_start": "2026-01-26T03:00:00",
            "date_end": "2026-01-27T02:59:59",
        }
        for k, v in direct_sdk_params.items():
            print(f"  {k}: {v}")

        print("\n--- COMPARISON RESULT ---")
        api_date_start = validated["date_start"]
        sdk_date_start = direct_sdk_params["date_start"]
        print(f"  API sends:        '{api_date_start}'")
        print(f"  Direct SDK sends: '{sdk_date_start}'")
        print(f"  ARE THEY EQUAL?   {api_date_start == sdk_date_start}")

        if api_date_start != sdk_date_start:
            print("\n  ⚠️  DIFFERENCE DETECTED!")
            print(f"  API has 'Z': {'Z' in api_date_start}")
            print(f"  SDK has 'Z': {'Z' in sdk_date_start}")

    def test_edge_case_events_at_boundary(self):
        """
        Show how small datetime differences could affect event counts.
        """
        print("\n" + "=" * 80)
        print("TEST: Edge case - events at date boundary")
        print("=" * 80)

        # If Redshift interprets dates differently based on Z suffix
        print("\nHypothetical scenario:")
        print("  If Redshift treats '2026-01-26T03:00:00' as local time (e.g., UTC-3)")
        print("  and '2026-01-26T03:00:00Z' as UTC, there's a 3-hour difference.")
        print("")
        print("  '2026-01-26T03:00:00' (local UTC-3) = '2026-01-26T06:00:00Z' (UTC)")
        print("  '2026-01-26T03:00:00Z' (UTC)        = '2026-01-26T03:00:00Z' (UTC)")
        print("")
        print("  Events between 03:00 and 06:00 UTC would be included/excluded differently!")


class TestWithDjangoSettings(TestCase):
    """Test with actual Django settings to see timezone behavior"""

    @override_settings(USE_TZ=True, TIME_ZONE="GMT")
    def test_drf_with_use_tz_true(self):
        """Test DRF behavior when USE_TZ=True (current setting)"""
        print("\n" + "=" * 80)
        print("TEST: DRF with USE_TZ=True, TIME_ZONE='GMT'")
        print("=" * 80)

        input_data = {"date_start": "2026-01-26T03:00:00", "date_end": "2026-01-27T02:59:59"}

        serializer = EventFilterSerializerTest(data=input_data)
        serializer.is_valid(raise_exception=True)
        ds = serializer.validated_data["date_start"]

        print(f"\n  Input: '2026-01-26T03:00:00' (no timezone)")
        print(f"  Result: {ds}")
        print(f"  tzinfo: {ds.tzinfo}")
        print(f"  Is aware: {ds.tzinfo is not None}")

        # Now normalize
        params = dict(serializer.validated_data)
        normalize_datetime_params_original(params)
        print(f"\n  After normalize: {params['date_start']}")


class TestTimezoneMiddlewareEffect(TestCase):
    """
    Test that simulates the TimezoneMiddleware effect on datetime parsing.
    
    This reproduces the bug where dates without timezone are interpreted
    as being in the org's timezone, causing a shift when converted to UTC.
    """

    @override_settings(USE_TZ=True)
    def test_org_timezone_causes_date_shift(self):
        """
        Test that proves: when org timezone is America/Sao_Paulo (UTC-3),
        a naive datetime '2026-01-26T03:00:00' becomes '2026-01-26T06:00:00Z'
        after the full flow.
        
        This is the ROOT CAUSE of the data divergence.
        """
        import pytz
        from django.utils import timezone as dj_timezone
        
        print("\n" + "=" * 80)
        print("TEST: Org timezone (UTC-3) causes 3-hour shift")
        print("=" * 80)
        
        # Simulate what TimezoneMiddleware does: activate org's timezone
        sao_paulo_tz = pytz.timezone("America/Sao_Paulo")
        dj_timezone.activate(sao_paulo_tz)
        
        try:
            # Input: date WITHOUT timezone (what the user sends)
            input_data = {
                "date_start": "2026-01-26T03:00:00",
                "date_end": "2026-01-27T02:59:59"
            }
            
            print(f"\n1. Input (no timezone): {input_data['date_start']}")
            print(f"   Active Django timezone: {dj_timezone.get_current_timezone()}")
            
            # DRF serializer parses the date
            serializer = EventFilterSerializerTest(data=input_data)
            serializer.is_valid(raise_exception=True)
            
            ds = serializer.validated_data["date_start"]
            print(f"\n2. After DRF DateTimeField:")
            print(f"   Value: {ds}")
            print(f"   tzinfo: {ds.tzinfo}")
            print(f"   Hour: {ds.hour}")
            
            # _normalize_datetime_params converts to UTC
            params = dict(serializer.validated_data)
            normalize_datetime_params_original(params)
            
            print(f"\n3. After _normalize_datetime_params:")
            print(f"   Value: {params['date_start']}")
            
            # THE ASSERTION: proves the bug
            expected_wrong_result = "2026-01-26T06:00:00Z"
            expected_correct_result = "2026-01-26T03:00:00Z"
            
            print(f"\n4. RESULT:")
            print(f"   Got:      '{params['date_start']}'")
            print(f"   Expected (wrong, bug): '{expected_wrong_result}'")
            print(f"   Expected (correct):    '{expected_correct_result}'")
            
            # This assertion PASSES, proving the bug exists
            self.assertEqual(
                params["date_start"], 
                expected_wrong_result,
                "Bug confirmed: date shifted 3 hours due to org timezone!"
            )
            
            print("\n   ✅ BUG CONFIRMED: Date shifted from 03:00 to 06:00 UTC!")
            print("   The API interprets naive dates as org timezone, not UTC.")
            
        finally:
            # Restore default timezone
            dj_timezone.deactivate()

    @override_settings(USE_TZ=True)
    def test_date_with_z_suffix_not_affected(self):
        """
        Test that dates WITH 'Z' suffix are NOT affected by org timezone.
        This is the workaround/fix.
        """
        import pytz
        from django.utils import timezone as dj_timezone
        
        print("\n" + "=" * 80)
        print("TEST: Date with Z suffix is NOT affected by org timezone")
        print("=" * 80)
        
        # Simulate TimezoneMiddleware
        sao_paulo_tz = pytz.timezone("America/Sao_Paulo")
        dj_timezone.activate(sao_paulo_tz)
        
        try:
            # Input: date WITH Z timezone (the fix)
            input_data = {
                "date_start": "2026-01-26T03:00:00Z",  # <-- WITH Z
                "date_end": "2026-01-27T02:59:59Z"
            }
            
            print(f"\n1. Input (WITH Z): {input_data['date_start']}")
            print(f"   Active Django timezone: {dj_timezone.get_current_timezone()}")
            
            serializer = EventFilterSerializerTest(data=input_data)
            serializer.is_valid(raise_exception=True)
            
            ds = serializer.validated_data["date_start"]
            print(f"\n2. After DRF DateTimeField:")
            print(f"   Value: {ds}")
            print(f"   tzinfo: {ds.tzinfo}")
            print(f"   Hour: {ds.hour}")
            
            params = dict(serializer.validated_data)
            normalize_datetime_params_original(params)
            
            print(f"\n3. After _normalize_datetime_params:")
            print(f"   Value: {params['date_start']}")
            
            # With Z suffix, the time should NOT shift
            expected = "2026-01-26T03:00:00Z"
            
            print(f"\n4. RESULT:")
            print(f"   Got:      '{params['date_start']}'")
            print(f"   Expected: '{expected}'")
            
            self.assertEqual(
                params["date_start"],
                expected,
                "Date with Z should not be affected by org timezone"
            )
            
            print("\n   ✅ CORRECT: Date with Z stays at 03:00 UTC!")
            print("   This is the fix: always send dates with Z suffix.")
            
        finally:
            dj_timezone.deactivate()

    @override_settings(USE_TZ=True)
    def test_comparison_with_and_without_z(self):
        """
        Direct comparison showing the difference between sending dates
        with and without Z suffix when org is in UTC-3.
        """
        import pytz
        from django.utils import timezone as dj_timezone
        
        print("\n" + "=" * 80)
        print("TEST: Side-by-side comparison WITH vs WITHOUT Z suffix")
        print("=" * 80)
        
        sao_paulo_tz = pytz.timezone("America/Sao_Paulo")
        dj_timezone.activate(sao_paulo_tz)
        
        try:
            # WITHOUT Z
            input_without_z = {"date_start": "2026-01-26T03:00:00", "date_end": "2026-01-27T02:59:59"}
            serializer1 = EventFilterSerializerTest(data=input_without_z)
            serializer1.is_valid(raise_exception=True)
            params1 = dict(serializer1.validated_data)
            normalize_datetime_params_original(params1)
            
            # WITH Z
            input_with_z = {"date_start": "2026-01-26T03:00:00Z", "date_end": "2026-01-27T02:59:59Z"}
            serializer2 = EventFilterSerializerTest(data=input_with_z)
            serializer2.is_valid(raise_exception=True)
            params2 = dict(serializer2.validated_data)
            normalize_datetime_params_original(params2)
            
            print(f"\nOrg timezone: America/Sao_Paulo (UTC-3)")
            print(f"\n{'Input':<35} {'Result sent to Datalake':<30}")
            print("-" * 65)
            print(f"{'2026-01-26T03:00:00 (no Z)':<35} {params1['date_start']:<30}")
            print(f"{'2026-01-26T03:00:00Z (with Z)':<35} {params2['date_start']:<30}")
            print("-" * 65)
            print(f"\nDifference: {params1['date_start']} vs {params2['date_start']}")
            print("           = 3 hours difference!")
            
            self.assertNotEqual(params1["date_start"], params2["date_start"])
            self.assertEqual(params1["date_start"], "2026-01-26T06:00:00Z")
            self.assertEqual(params2["date_start"], "2026-01-26T03:00:00Z")
            
            print("\n   ✅ Test passed: 3-hour difference confirmed!")
            
        finally:
            dj_timezone.deactivate()
