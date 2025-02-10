from kivy_ios.toolchain import PythonRecipe, CythonRecipe, Recipe, shprint
import os


class QuicklzRecipe(CythonRecipe):
    version = "1.5.0"
    url = "https://github.com/sergey-dryabzhinsky/python-quicklz/archive/refs/tags/v{version}.tar.gz"

    depends = ['python3']
    library = "libquicklz.a"

    def prebuild_platform(self, plat):
        if self.has_marker("patched"):
            return
        self.apply_patch(os.path.join(os.path.dirname(__file__), "patch_python3.diff"))
        self.set_marker("patched")

    python_depends = ['setuptools']
    call_hostpython_via_targetpython = False

    def get_recipe_env(self, arch=None):
        env = super().get_recipe_env(arch)
        env['OTHER_LDFLAGS'] += "-static"
        return env

recipe = QuicklzRecipe()
