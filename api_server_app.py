from multiprocessing import freeze_support

from server.run_api import main


if __name__ == "__main__":
    freeze_support()
    main()
