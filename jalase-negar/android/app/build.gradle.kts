plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "app.jalasenegar.jalase_negar"
    compileSdk = 36
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_11.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "app.jalasenegar.jalase_negar"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    packaging {
        resources {
            excludes += "**/libVkLayer_khronos_validation.so"
        }
        jniLibs {
            excludes += "**/x86_64/*.so"
            excludes += "**/armeabi-v7a/*.so"
        }
    }
}

flutter {
    source = "../.."
}

// Strip web-only assets from the APK (they come from the sherpa_onnx_web package)
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }.configureEach {
    doLast {
        val variant = name.replace("merge", "").replace("Assets", "")
        val flutterAssetsDir = layout.buildDirectory.dir("intermediates/flutter/${variant.lowercase()}/flutter_assets").get().asFile
        if (flutterAssetsDir.exists()) {
            delete(fileTree(flutterAssetsDir) {
                include("packages/sherpa_onnx_web/assets/*.wasm")
                include("packages/sherpa_onnx_web/assets/*.js")
            })
        }
    }
}
