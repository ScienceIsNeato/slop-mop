"""Dart/Flutter-specific checks."""

from slopmop.checks.dart.analyze import FlutterAnalyzeCheck
from slopmop.checks.dart.bogus_tests import DartBogusTestsCheck
from slopmop.checks.dart.coverage import DartCoverageCheck
from slopmop.checks.dart.format import DartFormatCheck
from slopmop.checks.dart.generated_artifacts import DartGeneratedArtifactsCheck
from slopmop.checks.dart.tests import FlutterTestsCheck

__all__ = [
    "FlutterAnalyzeCheck",
    "FlutterTestsCheck",
    "DartFormatCheck",
    "DartBogusTestsCheck",
    "DartCoverageCheck",
    "DartGeneratedArtifactsCheck",
]
