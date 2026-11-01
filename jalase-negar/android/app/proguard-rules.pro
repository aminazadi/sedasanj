# Flutter
-keep class io.flutter.app.** { *; }
-keep class io.flutter.plugin.** { *; }
-keep class io.flutter.util.** { *; }
-keep class io.flutter.view.** { *; }
-keep class io.flutter.** { *; }
-keep class io.flutter.plugins.** { *; }

# sherpa_onnx
-keep class com.k2fsa.sherpa.onnx.** { *; }

# Kotlin
-keepattributes *Annotation*
-keepattributes SourceFile,LineNumberTable

# Keep native methods
-keepclasseswithmembernames class * {
    native <methods>;
}

# Play Core / Split Install (used by Flutter deferred components)
-dontwarn com.google.android.play.core.**
