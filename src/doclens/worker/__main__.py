"""python -m doclens.worker {worker,dispatch}"""

from doclens.worker.celery_app import main

if __name__ == "__main__":
    main()
