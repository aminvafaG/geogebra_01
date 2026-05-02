/**
 * Precompiled [app-specs-convention.gradle.kts][App_specs_convention_gradle] script plugin.
 *
 * @see App_specs_convention_gradle
 */
public
class AppSpecsConventionPlugin : org.gradle.api.Plugin<org.gradle.api.Project> {
    override fun apply(target: org.gradle.api.Project) {
        try {
            Class
                .forName("App_specs_convention_gradle")
                .getDeclaredConstructor(org.gradle.api.Project::class.java, org.gradle.api.Project::class.java)
                .newInstance(target, target)
        } catch (e: java.lang.reflect.InvocationTargetException) {
            throw e.targetException
        }
    }
}
