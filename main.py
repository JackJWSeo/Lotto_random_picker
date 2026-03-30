import sys
from ui_main import LottoApp
from sphere_lotto_opengl import run_sphere_opengl
from ui_3d_cube_pg import run_3d_cube_pg

def main():
    if "--sphere" in sys.argv:
        run_sphere_opengl()
        return

    if "--cube" in sys.argv:
        run_3d_cube_pg()
        return

    app = LottoApp()
    app.mainloop()

if __name__ == "__main__":
    main()