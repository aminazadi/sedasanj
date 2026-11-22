allprojects {
    repositories {
        google()
        mavenCentral()
        // Store billing SDKs: Poolakey (Cafe Bazaar) is on JitPack, Myket has its own repository.
        maven { url = uri("https://jitpack.io") }
        maven { url = uri("https://maven.myket.ir") }
        maven {
            url = uri("https://mirrors.cloud.tencent.com/nexus/repository/maven-public/")
        }
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
// Plugins such as myket_iap pin Build Tools 36.0.0; use the installed 36.1.0 instead of
// requiring a download.
gradle.projectsEvaluated {
    subprojects {
        (extensions.findByName("android") as? com.android.build.gradle.BaseExtension)
            ?.buildToolsVersion = "36.1.0"
    }
}

subprojects {
    project.evaluationDependsOn(":app")
}
