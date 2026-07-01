cmake_minimum_required(VERSION 2.8.3)
project(baxter_chess)

find_package(catkin REQUIRED)
catkin_package()

catkin_install_python(PROGRAMS
  scripts/calibrate_board.py
  scripts/calibrate_home.py
  scripts/go_home.py
  scripts/gripper_setup.py
  scripts/move_piece.py
  scripts/test_square.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)

install(FILES
  scripts/chess_board.py
  scripts/baxter_motion.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
